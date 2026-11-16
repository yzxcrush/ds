/* ==========================================================================
 * Ds v0.1 —— 原生 C 参考驱动
 *
 * 组成：Arena 分配器 → 词法器 → 递归下降解析器 → 树遍历解释器 → CLI/REPL。
 * 定位：把「终端驱动」从 Python 换写成 C（无第三方依赖，仅 libc + libm）。
 *
 * 覆盖的核心子集：
 *   package / fn / let / var / 递归 / 闭包（函数值）
 *   字面量：int(10/0x/0b) / float / "str" / b"raw" / [数组] / {k:v} 映射
 *   语句：let var if/else while loop for-in break continue return 赋值(变量/下标)
 *   表达式：+ - * / % == != < > <= >= && || & | ^ ~ << >> 一元 +-!~ 调用 索引 管道 |>
 *   内建：println print len range str concat 以及 math.sqrt/round/floor/ceil/abs/pow
 * 明确不支持（会给出清晰错误，Python 参考实现可跑）：
 *   class/trait/impl/opt/res/try/catch/panic/match/宏/comptime/并发/内存原语等
 * ========================================================================== */
#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <glob.h>
#include <sys/stat.h>

#define DS_VERSION "0.1.0"
#define DS_MAX_MSG 1024

/* ------------------------------------------------------------------ */
/* 诊断 / 错误（用 longjmp 从任意深处回到运行入口）                    */
/* ------------------------------------------------------------------ */
static jmp_buf g_err;
static char g_errmsg[DS_MAX_MSG];
static const char *g_file = "<input>";
static int g_err_line, g_err_col;

static void ds_fail(int line, int col, const char *fmt, ...) {
    va_list ap;
    char body[DS_MAX_MSG];
    va_start(ap, fmt);
    vsnprintf(body, sizeof body, fmt, ap);
    va_end(ap);
    if (line > 0)
        snprintf(g_errmsg, sizeof g_errmsg, "%s:%d:%d: %s", g_file, line, col, body);
    else
        snprintf(g_errmsg, sizeof g_errmsg, "%s: %s", g_file, body);
    g_err_line = line;
    g_err_col = col;
    longjmp(g_err, 1);
}

/* ------------------------------------------------------------------ */
/* Arena 分配器：AST / 值 / 字符串统一从 arena 分配，进程退出时释放     */
/* ------------------------------------------------------------------ */
typedef struct ArenaChunk {
    struct ArenaChunk *next;
    size_t used, cap;
    unsigned char data[];
} ArenaChunk;

static ArenaChunk *g_arena;

static void *xalloc(size_t n) {
    n = (n + 15u) & ~(size_t)15u;
    if (g_arena == NULL || g_arena->used + n > g_arena->cap) {
        size_t cap = n > (size_t)64 * 1024 ? n : (size_t)64 * 1024;
        ArenaChunk *c = (ArenaChunk *)malloc(sizeof(ArenaChunk) + cap);
        if (!c) {
            fprintf(stderr, "ds: out of memory\n");
            exit(3);
        }
        c->next = g_arena;
        c->used = 0;
        c->cap = cap;
        g_arena = c;
    }
    void *p = g_arena->data + g_arena->used;
    g_arena->used += n;
    return p;
}

static char *xstrndup(const char *s, size_t n) {
    char *p = (char *)xalloc(n + 1);
    memcpy(p, s, n);
    p[n] = '\0';
    return p;
}

static char *xstrdup(const char *s) { return xstrndup(s, strlen(s)); }

static char *xsprintf(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    va_list ap2;
    va_copy(ap2, ap);
    int n = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (n < 0) n = 0;
    char *buf = (char *)xalloc((size_t)n + 1);
    vsnprintf(buf, (size_t)n + 1, fmt, ap2);
    va_end(ap2);
    return buf;
}

/* ------------------------------------------------------------------ */
/* 动态指针数组（AST 子节点/参数等；回收交给进程退出）                  */
/* ------------------------------------------------------------------ */
typedef struct PtrVec {
    void **items;
    int len, cap;
} PtrVec;

static void pv_push(PtrVec *v, void *item) {
    if (v->len == v->cap) {
        v->cap = v->cap ? v->cap * 2 : 4;
        v->items = (void **)realloc(v->items, sizeof(void *) * (size_t)v->cap);
        if (!v->items) {
            fprintf(stderr, "ds: out of memory\n");
            exit(3);
        }
    }
    v->items[v->len++] = item;
}

/* ------------------------------------------------------------------ */
/* 词法                                                               */
/* ------------------------------------------------------------------ */
enum {
    TK_EOF = 0, TK_INT, TK_FLOAT, TK_STR, TK_FSTRING, TK_BYTES,
    TK_IDENT, TK_KEYWORD, TK_OP, TK_PUNCT, TK_NL
};

typedef struct Tok {
    int kind;
    int line, col;
    const char *s; /* 文本/标识符/字符串内容 */
    int len;
    int64_t i;
    double f;
} Tok;

static Tok *g_toks;
static int g_ntoks, g_captoks;

static void tok_push(Tok t) {
    if (g_ntoks == g_captoks) {
        g_captoks = g_captoks ? g_captoks * 2 : 256;
        g_toks = (Tok *)realloc(g_toks, sizeof(Tok) * (size_t)g_captoks);
        if (!g_toks) {
            fprintf(stderr, "ds: out of memory\n");
            exit(3);
        }
    }
    g_toks[g_ntoks++] = t;
}

/* 77 个关键字（与规范 §1.3 一致；符号关键字 @ -> => |> 也在此表） */
static const char *g_keywords[] = {
    "fn", "let", "var", "type", "class", "trait", "impl", "mod", "package",
    "if", "else", "loop", "while", "for", "break", "continue", "return", "goto",
    "try", "catch", "panic", "recover", "assert", "res", "opt",
    "use", "as", "export", "pub", "priv", "prot", "static", "extern",
    "spawn", "go", "thread", "chan", "send", "recv", "mutex", "wait",
    "raw", "free", "alloc", "rc", "arc", "gc", "ptr", "ref", "mut",
    "@", "asm", "volatile", "at", "irq", "section", "packed",
    "comptime", "macro", "typeinfo", "attr",
    "self", "super", "new", "drop", "extends", "dyn",
    "match", "when", "where", "in", "is", "sizeof", "alignof",
    "->", "=>", "|>",
    NULL
};

static int is_keyword(const char *s, int len) {
    for (int i = 0; g_keywords[i]; i++) {
        const char *k = g_keywords[i];
        if ((int)strlen(k) == len && memcmp(k, s, (size_t)len) == 0) return 1;
    }
    return 0;
}

static int is_ident_start(int c) { return isascii(c) && (isalpha(c) || c == '_'); }
static int is_ident_part(int c) { return isascii(c) && (isalnum(c) || c == '_'); }

static void lex_source(const char *src) {
    const char *p = src;
    int line = 1;
    int line_start = 0;
    size_t n = strlen(src);

    while ((size_t)(p - src) < n) {
        unsigned char c = (unsigned char)*p;

        if (c == '\n') {
            Tok t = {TK_NL, line, (int)(p - src) - line_start + 1, "\n", 1, 0, 0.0};
            tok_push(t);
            p++;
            line++;
            line_start = (int)(p - src);
            continue;
        }
        if (c == ' ' || c == '\t' || c == '\r') { p++; continue; }

        /* 注释：块注释可嵌套 */
        if (c == '#' && p[1] == '|') {
            const char *q = p + 2;
            int depth = 1;
            while (*q) {
                if (q[0] == '#' && q[1] == '|') { depth++; q += 2; }
                else if (q[0] == '|' && q[1] == '#') {
                    depth--; q += 2;
                    if (depth == 0) break;
                } else {
                    if (*q == '\n') { line++; line_start = (int)(q + 1 - src); }
                    q++;
                }
            }
            if (depth != 0) ds_fail(line, (int)(p - src) - line_start + 1, "块注释 #| 未闭合");
            p = q;
            continue;
        }
        if (c == '#' || (c == '/' && p[1] == '/')) {
            while (*p && *p != '\n') p++;
            continue;
        }

        /* f-string：与普通字符串同样的转义扫描，但 token 类型为 TK_FSTRING */
        int is_fstr = 0;
        if ((c == 'f' || c == 'F') && p[1] == '"') { is_fstr = 1; p++; c = '"'; }

        /* 字符串 */
        if (c == '"') {
            const char *start = p++;
            char *buf = NULL;
            int cap = 0, len = 0;
            while (*p && *p != '"') {
                if (*p == '\n') ds_fail(line, (int)(p - src) - line_start + 1, "字符串不可含裸换行");
                int ch = (unsigned char)*p;
                if (ch == '\\') {
                    p++;
                    char esc = *p;
                    int out = -1;
                    switch (esc) {
                        case 'n': out = '\n'; p++; break;
                        case 'r': out = '\r'; p++; break;
                        case 't': out = '\t'; p++; break;
                        case '0': out = '\0'; p++; break;
                        case '\\': out = '\\'; p++; break;
                        case '"': out = '"'; p++; break;
                        case 'x': {
                            char hex[3] = {p[1], p[2], 0};
                            if (!isxdigit((unsigned char)hex[0]) || !isxdigit((unsigned char)hex[1]))
                                ds_fail(line, (int)(p - src) - line_start + 1, "非法 \\xNN 转义");
                            out = (int)strtol(hex, NULL, 16);
                            p += 3;
                            break;
                        }
                        case 'u': {
                            if (p[1] != '{')
                                ds_fail(line, (int)(p - src) - line_start + 1, "非法 \\u{...} 转义");
                            const char *q = p + 2;
                            unsigned long cp = strtoul(q, NULL, 16);
                            while (*q && *q != '}') q++;
                            if (*q != '}') ds_fail(line, (int)(p - src) - line_start + 1, "非法 \\u{...} 转义");
                            p = q + 1;
                            if (len + 4 >= cap) { cap = cap ? cap * 2 : 32; buf = (char *)xalloc((size_t)cap); }
                            if (cp < 0x80) buf[len++] = (char)cp;
                            else if (cp < 0x800) {
                                buf[len++] = (char)(0xC0 | (cp >> 6));
                                buf[len++] = (char)(0x80 | (cp & 0x3F));
                            } else if (cp < 0x10000) {
                                buf[len++] = (char)(0xE0 | (cp >> 12));
                                buf[len++] = (char)(0x80 | ((cp >> 6) & 0x3F));
                                buf[len++] = (char)(0x80 | (cp & 0x3F));
                            } else {
                                buf[len++] = (char)(0xF0 | (cp >> 18));
                                buf[len++] = (char)(0x80 | ((cp >> 12) & 0x3F));
                                buf[len++] = (char)(0x80 | ((cp >> 6) & 0x3F));
                                buf[len++] = (char)(0x80 | (cp & 0x3F));
                            }
                            continue;
                        }
                        default:
                            ds_fail(line, (int)(p - src) - line_start + 1, "未知转义 \\%c", esc);
                    }
                    if (out == -1) continue;
                    ch = out;
                }
                if (len + 4 >= cap) { cap = cap ? cap * 2 : 32; buf = (char *)xalloc((size_t)cap); }
                buf[len++] = (char)ch;
                p++;
            }
            if (*p != '"') ds_fail(line, (int)(start - src) - line_start + 1, "字符串未闭合");
            p++;
            if (!buf) { cap = 1; buf = (char *)xalloc(1); }
            buf[len] = '\0';
            Tok t = {is_fstr ? TK_FSTRING : TK_STR, line,
                     (int)(start - src) - line_start + 1, buf, len, 0, 0.0};
            tok_push(t);
            continue;
        }

        /* 原始字节串 b"..."（不做转义） */
        if (c == 'b' && p[1] == '"') {
            const char *start = p;
            p += 2;
            const char *body = p;
            while (*p && *p != '"') p++;
            if (*p != '"') ds_fail(line, (int)(start - src) - line_start + 1, "字节串未闭合");
            int blen = (int)(p - body);
            p++;
            Tok t = {TK_BYTES, line, (int)(start - src) - line_start + 1, xstrndup(body, (size_t)blen), blen, 0, 0.0};
            tok_push(t);
            continue;
        }

        /* 原始标识符 `名` */
        if (c == '`') {
            const char *start = p++;
            const char *body = p;
            while (*p && *p != '`') p++;
            if (*p != '`' || p == body)
                ds_fail(line, (int)(start - src) - line_start + 1, "原始标识符必须非空且以反引号闭合");
            int len = (int)(p - body);
            p++;
            Tok t = {TK_IDENT, line, (int)(start - src) - line_start + 1, xstrndup(body, (size_t)len), len, 0, 0.0};
            tok_push(t);
            continue;
        }

        /* 数字 */
        if (isdigit(c)) {
            const char *start = p;
            int col = (int)(p - src) - line_start + 1;
            if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
                p += 2;
                const char *digits = p;
                while (isxdigit((unsigned char)*p) || *p == '_') p++;
                if (p == digits) ds_fail(line, col, "十六进制字面量缺少数字");
                int64_t v = 0;
                for (const char *q = digits; q < p; q++)
                    if (*q != '_') {
                        int d = isdigit((unsigned char)*q) ? *q - '0' : (tolower((unsigned char)*q) - 'a' + 10);
                        v = v * 16 + d;
                    }
                Tok t = {TK_INT, line, col, xstrndup(start, (size_t)(p - start)), (int)(p - start), v, 0.0};
                tok_push(t);
                continue;
            }
            if (p[0] == '0' && (p[1] == 'b' || p[1] == 'B')) {
                p += 2;
                const char *digits = p;
                while (*p == '0' || *p == '1' || *p == '_') p++;
                if (p == digits) ds_fail(line, col, "二进制字面量缺少 0/1");
                int64_t v = 0;
                for (const char *q = digits; q < p; q++)
                    if (*q != '_') v = v * 2 + (*q - '0');
                Tok t = {TK_INT, line, col, xstrndup(start, (size_t)(p - start)), (int)(p - start), v, 0.0};
                tok_push(t);
                continue;
            }
            bool is_float = false;
            while (isdigit((unsigned char)*p) || *p == '_') p++;
            if (*p == '.' && isdigit((unsigned char)p[1])) {
                is_float = true;
                p++;
                while (isdigit((unsigned char)*p) || *p == '_') p++;
            }
            if (*p == 'e' || *p == 'E') {
                const char *save = p;
                p++;
                if (*p == '+' || *p == '-') p++;
                if (isdigit((unsigned char)*p)) {
                    is_float = true;
                    while (isdigit((unsigned char)*p)) p++;
                } else {
                    p = save;
                }
            }
            char *raw = xstrndup(start, (size_t)(p - start));
            char clean[128];
            int ci = 0;
            for (const char *q = raw; *q && ci < 127; q++)
                if (*q != '_') clean[ci++] = *q;
            clean[ci] = '\0';
            Tok t;
            memset(&t, 0, sizeof t);
            t.line = line;
            t.col = col;
            t.s = raw;
            t.len = (int)(p - start);
            if (is_float) {
                t.kind = TK_FLOAT;
                t.f = strtod(clean, NULL);
            } else {
                t.kind = TK_INT;
                t.i = strtoll(clean, NULL, 10);
            }
            tok_push(t);
            continue;
        }

        /* 标识符 / 关键字 */
        if (is_ident_start(c)) {
            const char *start = p;
            int col = (int)(p - src) - line_start + 1;
            while (is_ident_part((unsigned char)*p)) p++;
            int len = (int)(p - start);
            Tok t = {(is_keyword(start, len) ? TK_KEYWORD : TK_IDENT), line, col,
                     xstrndup(start, (size_t)len), len, 0, 0.0};
            tok_push(t);
            continue;
        }

        /* 运算符（最长匹配） */
        {
            static const char *ops[] = {
                "|>", "->", "=>", "<<=", ">>=", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
                "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "..",
                "+", "-", "*", "/", "%", "=", "!", "<", ">", "&", "|", "^", "~", ".",
                "@", "\\", "?", NULL};
            int matched = 0;
            for (int i = 0; ops[i]; i++) {
                size_t l = strlen(ops[i]);
                if (strncmp(p, ops[i], l) == 0) {
                    int col = (int)(p - src) - line_start + 1;
                    int kw = (strcmp(ops[i], "@") == 0 || strcmp(ops[i], "->") == 0 ||
                              strcmp(ops[i], "=>") == 0 || strcmp(ops[i], "|>") == 0);
                    Tok t = {kw ? TK_KEYWORD : TK_OP, line, col, ops[i], (int)l, 0, 0.0};
                    tok_push(t);
                    p += l;
                    matched = 1;
                    break;
                }
            }
            if (matched) continue;
        }

        /* 标点 */
        if (strchr("(){}[],:;", (int)c)) {
            int col = (int)(p - src) - line_start + 1;
            Tok t = {TK_PUNCT, line, col, xstrndup(p, 1), 1, 0, 0.0};
            tok_push(t);
            p++;
            continue;
        }

        ds_fail(line, (int)(p - src) - line_start + 1, "未知字符 '%c'（Ds 标识符仅 ASCII）", c);
    }

    Tok eof = {TK_EOF, line, (int)(p - src) - line_start + 1, "<eof>", 5, 0, 0.0};
    tok_push(eof);
}

/* ------------------------------------------------------------------ */
/* AST                                                                */
/* ------------------------------------------------------------------ */
enum {
    ND_PROGRAM, ND_PACKAGE, ND_FN, ND_LET, ND_ASSIGN, ND_BLOCK,
    ND_IF, ND_WHILE, ND_LOOP, ND_FOR, ND_BREAK, ND_CONTINUE, ND_RETURN, ND_EXPRSTMT,
    ND_LIT_INT, ND_LIT_FLOAT, ND_LIT_STR, ND_LIT_BYTES, ND_LIT_BOOL,
    ND_ARRAY, ND_MAP, ND_VAR, ND_BINARY, ND_UNARY, ND_CALL, ND_INDEX,
    ND_IFEXPR, ND_BLOCKEXPR, ND_LOOPEXPR, ND_USE
};

typedef struct Node Node;
typedef struct Param {
    const char *name;
    Node *def;
    int is_mut;
    const char *type;
} Param;

struct Node {
    int kind;
    int line, col;
    const char *name;   /* 变量/函数/包名、二元运算符名 */
    const char *s;      /* 字符串/字节串字面量内容 */
    int slen;
    int64_t ival;
    double fval;
    int bval;           /* bool 字面量 / let 是否可变 */
    Node *a, *b, *c, *d;
    Node **items;
    int nitems;
    Node **keys;
    int nkeys;
    Param *params;
    int nparams;
    const char *type_name;   /* 返回类型/标注类型（仅基础名，供静态检查） */
};

static Node *node_new(int kind, int line, int col) {
    Node *n = (Node *)xalloc(sizeof(Node));
    memset(n, 0, sizeof *n);
    n->kind = kind;
    n->line = line;
    n->col = col;
    return n;
}

static void node_push(Node *n, Node *child) {
    n->items = (Node **)realloc(n->items, sizeof(Node *) * (size_t)(n->nitems + 1));
    if (!n->items) { fprintf(stderr, "ds: out of memory\n"); exit(3); }
    n->items[n->nitems++] = child;
}

static void node_key_push(Node *n, Node *key) {
    n->keys = (Node **)realloc(n->keys, sizeof(Node *) * (size_t)(n->nkeys + 1));
    if (!n->keys) { fprintf(stderr, "ds: out of memory\n"); exit(3); }
    n->keys[n->nkeys++] = key;
}

/* ------------------------------------------------------------------ */
/* 解析器                                                             */
/* ------------------------------------------------------------------ */
static int P_POS;

static Tok *cur(void) { return &g_toks[P_POS]; }
static Tok *peek(int k) {
    int i = P_POS + k;
    if (i >= g_ntoks) i = g_ntoks - 1;
    return &g_toks[i];
}
static void adv(void) {
    if (g_toks[P_POS].kind != TK_EOF) P_POS++;
}
static void skip_nl(void) {
    while (cur()->kind == TK_NL) adv();
}
static int tok_is(int kind, const char *text) {
    Tok *t = cur();
    return t->kind == kind && t->len == (int)strlen(text) && memcmp(t->s, text, (size_t)t->len) == 0;
}
static int is_kw(const char *text) { return tok_is(TK_KEYWORD, text); }
static int is_op(const char *text) { return tok_is(TK_OP, text); }
static int is_punct(char ch) {
    Tok *t = cur();
    return t->kind == TK_PUNCT && t->s[0] == ch;
}
static void expect_punct(char ch, const char *what) {
    skip_nl();
    if (!is_punct(ch)) ds_fail(cur()->line, cur()->col, "期望 '%c'（%s），得到 '%.*s'", ch, what, cur()->len, cur()->s);
    adv();
}
static const char *expect_ident(const char *what) {
    const char *name = NULL;
    for (;;) {
        Tok *t = cur();
        if (t->kind == TK_IDENT) { name = xstrndup(t->s, (size_t)t->len); break; }
        /* 方法名等允许关键字（本子集只用到 new/drop 之外的少数；直接报错） */
        ds_fail(t->line, t->col, "期望 %s，得到 '%.*s'", what, t->len, t->s);
    }
    adv();
    return name;
}

static int prec_of(const char *op) {
    if (strcmp(op, "|>") == 0) return 1;
    if (strcmp(op, "..") == 0) return 2;
    if (strcmp(op, "||") == 0) return 2;
    if (strcmp(op, "&&") == 0) return 3;
    if (strcmp(op, "|") == 0) return 4;
    if (strcmp(op, "^") == 0) return 5;
    if (strcmp(op, "&") == 0) return 6;
    if (strcmp(op, "==") == 0 || strcmp(op, "!=") == 0) return 7;
    if (strcmp(op, "<") == 0 || strcmp(op, ">") == 0 || strcmp(op, "<=") == 0 || strcmp(op, ">=") == 0) return 8;
    if (strcmp(op, "<<") == 0 || strcmp(op, ">>") == 0) return 9;
    if (strcmp(op, "+") == 0 || strcmp(op, "-") == 0) return 10;
    if (strcmp(op, "*") == 0 || strcmp(op, "/") == 0 || strcmp(op, "%") == 0) return 11;
    return 0;
}

static int g_flow = 0;

static void setup_flow(const char *file, const char *src) {
    const char *q = src;
    while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r') q++;
    g_flow = (file && strstr(file, ".dsf") != NULL) ||
             *q == '\\' || strncmp(q, "#!flow", 6) == 0;
}

static int is_compound_op(const char *op) {
    static const char *ops[] = {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", NULL};
    for (int i = 0; ops[i]; i++) if (strcmp(op, ops[i]) == 0) return 1;
    return 0;
}

static void skip_type(void) {
    skip_nl();
    int depth = 0;
    for (;;) {
        Tok *t = cur();
        if (t->kind == TK_EOF) return;
        if (t->kind == TK_PUNCT) {
            char ch = t->s[0];
            if (ch == '(' || ch == '[') { depth++; adv(); continue; }
            if (ch == '{') {
                if (depth == 0) return;   /* 返回类型之后是函数体块 */
                depth++;
                adv();
                continue;
            }
            if (ch == ')' || ch == ']' || ch == '}') {
                if (depth == 0) return;
                depth--;
                adv();
                continue;
            }
            if (depth == 0 && (ch == ',' || ch == ';' || ch == ':')) return;
        }
        if (t->kind == TK_KEYWORD && depth == 0) {
            if (strcmp(t->s, "where") == 0) return;
            if (strcmp(t->s, "->") == 0) { adv(); continue; }
        }
        if (t->kind == TK_OP && depth == 0 && strcmp(t->s, "=") == 0) return;
        if (t->kind == TK_NL && depth == 0) return;
        adv();
    }
}

static const char *read_type_tag(void) {
    skip_nl();
    Tok *t = cur();
    const char *tag = NULL;
    if (t->kind == TK_IDENT || t->kind == TK_KEYWORD)
        tag = xstrndup(t->s, (size_t)t->len);
    skip_type();
    return tag;
}

static Node *parse_block(void);
static Node *parse_body(void);
static Node *parse_fstring(Tok *t);
static Node *parse_fn_flow(void);
static Node *parse_flow_body(void);
static Node *parse_flow_if(void);
static Node *make_var_node(const char *name, int line, int col);
static Node *parse_expr(int min_prec);
static Node *parse_stmt(int top_level);
static Node *parse_fn(void);
static Node *make_noop_stmt(int line, int col);
static Node *parse_static_binding(Tok *at);
static Node *parse_at_item(void);
static Node *parse_let(int top_level);

/* 本子集不支持的声明/语句：给出清晰错误（避免静默误编译） */
static const char *g_unsupported[] = {
    "type", "class", "trait", "impl", "mod", "use", "export", "pub", "priv", "prot",
    "static", "extern", "macro", "attr", "section", "comptime", "try", "catch",
    "panic", "recover", "assert", "spawn", "go", "thread", "chan", "send", "recv",
    "mutex", "wait", "alloc", "free", "rc", "arc", "gc", "raw", "volatile", "asm",
    "irq", "at", "packed", "dyn", "self", "super", "new", "drop", "extends",
    "match", "when", "where", "is", "sizeof", "alignof", "goto", "res", "opt",
    NULL
};

static void reject_unsupported(void) {
    Tok *t = cur();
    if (t->kind != TK_KEYWORD) return;
    for (int i = 0; g_unsupported[i]; i++) {
        const char *k = g_unsupported[i];
        if ((int)strlen(k) == t->len && memcmp(k, t->s, (size_t)t->len) == 0)
            ds_fail(t->line, t->col,
                    "C 驱动 v0.1 暂不支持 `%s`（Python 参考实现支持；C 版聚焦核心子集）", k);
    }
}

static Node *parse_params_and_body(Node *fn) {
    expect_punct('(', "函数参数表");
    PtrVec params = {0};
    PtrVec defaults = {0};
    PtrVec types = {0};
    skip_nl();
    if (!is_punct(')')) {
        for (;;) {
            skip_nl();
            int p_mut = 0;
            if (is_kw("mut") || is_kw("ref")) {
                if (is_kw("mut")) p_mut = 1;
                adv();
                skip_nl();
            }
            Tok *t = cur();
            if (t->kind == TK_IDENT && t->len == 1 && t->s[0] == '_') {
                /* 忽略参数 */
                adv();
            } else if (t->kind != TK_IDENT) {
                ds_fail(t->line, t->col, "期望参数名，得到 '%.*s'", t->len, t->s);
            }
            const char *name = (t->kind == TK_IDENT) ? xstrndup(t->s, (size_t)t->len) : "_";
            if (t->kind == TK_IDENT) adv();
            skip_nl();
            Node *def = NULL;
            const char *ptype = NULL;
            if (is_punct(':')) {
                adv();
                ptype = read_type_tag();
            }
            skip_nl();
            if (is_op("=")) {
                adv();
                def = parse_expr(1);
            }
            pv_push(&params, (void *)xstrdup(name));
            pv_push(&defaults, def);
            pv_push(&types, (void *)ptype);
            (void)p_mut;
            skip_nl();
            if (is_punct(',')) { adv(); continue; }
            break;
        }
    }
    expect_punct(')', "参数表结束");
    skip_nl();
    if (is_kw("->")) {
        adv();
        fn->type_name = read_type_tag();
    }
    skip_nl();
    if (is_kw("where")) {
        while (!is_punct('{') && cur()->kind != TK_EOF) adv();
    }
    skip_nl();
    fn->nparams = params.len;
    fn->params = (Param *)xalloc(sizeof(Param) * (size_t)(params.len ? params.len : 1));
    for (int i = 0; i < params.len; i++) {
        fn->params[i].name = (const char *)params.items[i];
        fn->params[i].def = (Node *)defaults.items[i];
        fn->params[i].is_mut = 0;
        fn->params[i].type = (const char *)types.items[i];
    }
    free(params.items);
    free(defaults.items);
    free(types.items);
    if (is_op("=")) {
        adv();
        skip_nl();
        fn->a = parse_expr(1);
    } else if (is_punct(':')) {
        Tok *et = cur();
        adv();
        skip_nl();
        Node *blk = node_new(ND_BLOCK, et->line, et->col);
        Node *st = parse_stmt(0);
        if (st) node_push(blk, st);
        fn->a = blk;
    } else {
        fn->a = parse_body();
    }
    return fn;
}

static Node *parse_fn(void) {
    Tok *t = cur();
    adv(); /* fn */
    Node *fn = node_new(ND_FN, t->line, t->col);
    fn->name = expect_ident("函数名");
    return parse_params_and_body(fn);
}

static Node *parse_if_expr(void) {
    Tok *t = cur();
    adv(); /* if */
    Node *node = node_new(ND_IFEXPR, t->line, t->col);
    node->a = parse_expr(1);
    node->b = parse_body();
    skip_nl();
    if (is_kw("else")) {
        adv();
        skip_nl();
        if (is_kw("if")) node->c = parse_if_expr();
        else node->c = parse_body();
    }
    return node;
}

static Node *parse_let(int top_level) {
    Tok *t = cur();
    int is_mut = is_kw("var");
    adv(); /* let / var */
    Node *n = node_new(ND_LET, t->line, t->col);
    n->name = expect_ident("变量名");
    n->bval = is_mut;
    skip_nl();
    if (is_punct(':')) {
        adv();
        n->type_name = read_type_tag();
    }
    skip_nl();
    if (is_op("=")) {
        adv();
        n->a = parse_expr(1);
    }
    (void)top_level;
    return n;
}

static Node *parse_stmt(int top_level) {
    skip_nl();
    Tok *t = cur();
    if (t->kind == TK_EOF) return NULL;

    if (g_flow && t->kind == TK_OP && strcmp(t->s, "?") == 0) return parse_flow_if();
    if (g_flow && t->kind == TK_OP && strcmp(t->s, "^") == 0) {
        adv();
        Node *n = node_new(ND_RETURN, t->line, t->col);
        if (!is_punct('}') && !is_punct(';') && !(cur()->kind == TK_OP && strcmp(cur()->s, ".") == 0) &&
            cur()->kind != TK_NL && cur()->kind != TK_EOF)
            n->a = parse_expr(1);
        return n;
    }
    if (is_punct('{')) return parse_block();
    if (is_kw("@")) {
        adv();
        skip_nl();
        if (is_kw("asm")) {
            adv();
            skip_nl();
            if (cur()->kind == TK_STR) adv();
            else if (is_punct('(')) {
                int depth = 1; adv();
                while (depth > 0 && cur()->kind != TK_EOF) {
                    if (is_punct('(')) depth++;
                    else if (is_punct(')')) depth--;
                    adv();
                }
            }
            return make_noop_stmt(t->line, t->col);
        }
        if (is_kw("static")) {
            adv(); skip_nl();
            if (is_kw("var") || is_kw("let")) return parse_let(top_level);
            return parse_static_binding(t);
        }
        if (is_kw("unsafe")) {
            adv(); skip_nl();
            if (is_punct('{')) return parse_block();
            return parse_stmt(top_level);
        }
        ds_fail(t->line, t->col, "未知 @ 属性");
    }
    if (is_kw("let") || is_kw("var")) return parse_let(top_level);

    if (is_kw("if")) return parse_if_expr();

    if (is_kw("while")) {
        adv();
        Node *n = node_new(ND_WHILE, t->line, t->col);
        n->a = parse_expr(1);
        n->b = parse_body();
        return n;
    }
    if (is_kw("loop")) {
        adv();
        Node *n = node_new(ND_LOOP, t->line, t->col);
        n->b = parse_body();
        return n;
    }
    if (is_kw("for")) {
        adv();
        Node *n = node_new(ND_FOR, t->line, t->col);
        skip_nl();
        Tok *p = cur();
        if (p->kind == TK_IDENT) {
            n->name = (p->len == 1 && p->s[0] == '_') ? "_" : xstrndup(p->s, (size_t)p->len);
            adv();
        } else {
            ds_fail(p->line, p->col, "for 循环本子集只支持 `for 名字 in ...`");
        }
        skip_nl();
        if (!is_kw("in")) ds_fail(cur()->line, cur()->col, "for 需要 `in`");
        adv();
        n->a = parse_expr(1);
        n->b = parse_body();
        return n;
    }
    if (is_kw("break")) {
        adv();
        Node *n = node_new(ND_BREAK, t->line, t->col);
        if (!is_punct('}') && !is_punct(';') && cur()->kind != TK_NL && cur()->kind != TK_EOF)
            n->a = parse_expr(1);
        return n;
    }
    if (is_kw("continue")) {
        adv();
        return node_new(ND_CONTINUE, t->line, t->col);
    }
    if (is_kw("return")) {
        adv();
        Node *n = node_new(ND_RETURN, t->line, t->col);
        if (!is_punct('}') && !is_punct(';') && cur()->kind != TK_NL && cur()->kind != TK_EOF)
            n->a = parse_expr(1);
        return n;
    }
    if (is_kw("goto")) {
        ds_fail(t->line, t->col, "C 驱动 v0.1 暂不支持 `goto`");
    }
    reject_unsupported();

    /* 表达式 / 赋值 */
    Node *left = parse_expr(1);
    if (cur()->kind == TK_OP && is_compound_op(cur()->s)) {
        adv();
        Node *n = node_new(ND_ASSIGN, t->line, t->col);
        n->name = xstrdup(cur() ? "" : "");
        n->name = xstrndup(g_toks[P_POS - 1].s, (size_t)g_toks[P_POS - 1].len);
        n->a = left;
        n->b = parse_expr(1);
        if (left->kind != ND_VAR && left->kind != ND_INDEX)
            ds_fail(left->line, left->col, "赋值目标只能是变量或数组/映射下标");
        return n;
    }
    if (is_op("=")) {
        adv();
        Node *n = node_new(ND_ASSIGN, t->line, t->col);
        n->a = left;
        n->b = parse_expr(1);
        if (left->kind != ND_VAR && left->kind != ND_INDEX)
            ds_fail(left->line, left->col, "赋值目标只能是变量或数组/映射下标");
        return n;
    }
    Node *wrap = node_new(ND_EXPRSTMT, left->line, left->col);
    wrap->a = left;
    return wrap;
}

static Node *parse_block(void) {
    skip_nl();
    Tok *t = cur();
    if (!is_punct('{')) ds_fail(t->line, t->col, "期望块 `{`，得到 '%.*s'", t->len, t->s);
    adv();
    Node *block = node_new(ND_BLOCK, t->line, t->col);
    for (;;) {
        skip_nl();
        while (is_punct(';')) { adv(); skip_nl(); }
        if (cur()->kind == TK_EOF) ds_fail(t->line, t->col, "块未闭合（缺少 '}'）");
        if (is_punct('}')) { adv(); break; }
        Node *stmt = parse_stmt(0);
        if (stmt) node_push(block, stmt);
    }
    return block;
}

/* 数组字面量：[a b, c] */
static Node *parse_array_lit(void) {
    Tok *t = cur();
    adv(); /* [ */
    Node *n = node_new(ND_ARRAY, t->line, t->col);
    for (;;) {
        skip_nl();
        while (is_punct(',')) { adv(); skip_nl(); }
        if (is_punct(']')) { adv(); break; }
        if (cur()->kind == TK_EOF) ds_fail(t->line, t->col, "数组字面量未闭合");
        node_push(n, parse_expr(1));
        skip_nl();
        if (is_punct(',')) { adv(); continue; }
    }
    return n;
}

/* 映射字面量：{k: v, ...} / 空映射 {:} / 否则块表达式 */
static Node *parse_brace_expr(void) {
    Tok *t = cur(); /* '{' */
    Tok *after = peek(1);
    Tok *after2 = peek(2);

    /* { } -> 空块表达式 */
    if (after->kind == TK_PUNCT && after->s[0] == '}') {
        adv();
        adv();
        Node *blk = node_new(ND_BLOCKEXPR, t->line, t->col);
        blk->b = node_new(ND_BLOCK, t->line, t->col);
        return blk;
    }
    /* { : } -> 空映射 */
    if (after->kind == TK_PUNCT && after->s[0] == ':' &&
        after2->kind == TK_PUNCT && after2->s[0] == '}') {
        adv();
        adv();
        expect_punct('}', "空映射");
        return node_new(ND_MAP, t->line, t->col);
    }
    /* { key : value ... } -> 映射字面量 */
    int looks_like_map = (after->kind == TK_IDENT || after->kind == TK_STR ||
                          after->kind == TK_INT || after->kind == TK_FLOAT) &&
                         after2->kind == TK_PUNCT && after2->s[0] == ':';
    if (looks_like_map) {
        adv(); /* { */
        Node *map = node_new(ND_MAP, t->line, t->col);
        for (;;) {
            skip_nl();
            while (is_punct(',')) { adv(); skip_nl(); }
            if (is_punct('}')) { adv(); break; }
            Node *key = parse_expr(1);
            skip_nl();
            expect_punct(':', "映射键值对");
            Node *val = parse_expr(1);
            node_key_push(map, key);
            node_push(map, val);
            skip_nl();
            if (is_punct(',')) { adv(); continue; }
        }
        return map;
    }
    /* 其余按块表达式 */
    adv(); /* { */
    Node *blk = node_new(ND_BLOCKEXPR, t->line, t->col);
    Node *body = node_new(ND_BLOCK, t->line, t->col);
    for (;;) {
        skip_nl();
        while (is_punct(';')) { adv(); skip_nl(); }
        if (is_punct('}')) { adv(); break; }
        if (cur()->kind == TK_EOF) ds_fail(t->line, t->col, "块表达式未闭合");
        Node *stmt = parse_stmt(0);
        if (stmt) node_push(body, stmt);
    }
    blk->b = body;
    return blk;
}

static Node *make_var_node(const char *name, int line, int col) {
    Node *v = node_new(ND_VAR, line, col);
    v->name = name;
    return v;
}

static Node *concat_nodes(Node *a, Node *b, int line, int col) {
    if (!a) return b;
    if (!b) return a;
    Node *bin = node_new(ND_BINARY, line, col);
    bin->name = "+";
    bin->a = a;
    bin->b = b;
    return bin;
}

static Node *parse_embedded_expr(const char *src, int len, int line, int col) {
    Tok *save_toks = g_toks;
    int save_n = g_ntoks, save_cap = g_captoks, save_pos = P_POS;
    g_toks = NULL;
    g_ntoks = 0;
    g_captoks = 0;
    char *buf = (char *)xalloc((size_t)len + 1);
    memcpy(buf, src, (size_t)len);
    buf[len] = '\0';
    lex_source(buf);
    P_POS = 0;
    Node *expr = parse_expr(1);
    free(g_toks);
    g_toks = save_toks;
    g_ntoks = save_n;
    g_captoks = save_cap;
    P_POS = save_pos;
    (void)line;
    (void)col;
    return expr;
}

static Node *parse_fstring(Tok *t) {
    const char *raw = t->s;
    int n = t->len;
    Node *result = NULL;
    char *buf = (char *)xalloc((size_t)n + 1);
    int blen = 0;
    for (int i = 0; i < n;) {
        char ch = raw[i];
        if (ch == '{' && i + 1 < n && raw[i + 1] == '{') { buf[blen++] = '{'; i += 2; continue; }
        if (ch == '}' && i + 1 < n && raw[i + 1] == '}') { buf[blen++] = '}'; i += 2; continue; }
        if (ch == '{') {
            int j = i + 1;
            while (j < n && raw[j] != '}') j++;
            if (j >= n) ds_fail(t->line, t->col, "f-string 插值未闭合");
            if (blen > 0) {
                Node *lit = node_new(ND_LIT_STR, t->line, t->col);
                lit->s = xstrndup(buf, (size_t)blen);
                lit->slen = blen;
                result = concat_nodes(result, lit, t->line, t->col);
                blen = 0;
            }
            Node *expr = parse_embedded_expr(raw + i + 1, j - i - 1, t->line, t->col);
            Node *call = node_new(ND_CALL, t->line, t->col);
            call->a = make_var_node("str", t->line, t->col);
            node_push(call, expr);
            result = concat_nodes(result, call, t->line, t->col);
            i = j + 1;
            continue;
        }
        buf[blen++] = ch;
        i++;
    }
    if (blen > 0) {
        Node *lit = node_new(ND_LIT_STR, t->line, t->col);
        lit->s = xstrndup(buf, (size_t)blen);
        lit->slen = blen;
        result = concat_nodes(result, lit, t->line, t->col);
    }
    if (!result) {
        Node *lit = node_new(ND_LIT_STR, t->line, t->col);
        lit->s = "";
        lit->slen = 0;
        result = lit;
    }
    return result;
}


/* ---------------- Flow 写法 ---------------- */
static int flow_atom_start(void) {
    Tok *t = cur();
    if (t->kind == TK_INT || t->kind == TK_FLOAT || t->kind == TK_STR ||
        t->kind == TK_FSTRING || t->kind == TK_BYTES || t->kind == TK_IDENT)
        return 1;
    if (t->kind == TK_PUNCT && (t->s[0] == '(' || t->s[0] == '[')) return 1;
    if (g_flow && t->kind == TK_OP && strcmp(t->s, "?") == 0) return 1;
    return 0;
}

static Node *parse_flow_body(void) {
    if (is_punct('{')) return parse_block();
    if (is_punct(':')) {
        Tok *t = cur();
        adv();
        skip_nl();
        Node *blk = node_new(ND_BLOCK, t->line, t->col);
        Node *st = parse_stmt(0);
        if (st) node_push(blk, st);
        return blk;
    }
    if (cur()->kind != TK_NL) {
        Tok *t = cur();
        Node *blk = node_new(ND_BLOCK, t->line, t->col);
        Node *st = parse_stmt(0);
        if (st) node_push(blk, st);
        return blk;
    }
    Tok *t = cur();
    Node *blk = node_new(ND_BLOCK, t->line, t->col);
    skip_nl();
    while (cur()->kind != TK_EOF) {
        if (cur()->kind == TK_OP && strcmp(cur()->s, ".") == 0) { adv(); return blk; }
        if (is_kw("else")) return blk;
        Node *st = parse_stmt(0);
        if (st) node_push(blk, st);
        skip_nl();
    }
    ds_fail(t->line, t->col, "Flow 语句块缺少 '.' 终止符");
    return blk;
}

static Node *parse_flow_if(void) {
    Tok *t = cur();
    adv(); /* ? */
    Node *node = node_new(ND_IFEXPR, t->line, t->col);
    node->a = parse_expr(1);
    node->b = parse_flow_body();
    if (is_punct(';')) {
        adv();
        node->c = parse_flow_body();
    } else {
        skip_nl();
        if (is_kw("else")) {
            adv();
            int save = P_POS;
            skip_nl();
            if (cur()->kind == TK_OP && strcmp(cur()->s, "?") == 0) {
                node->c = parse_flow_if();   /* else-if：无需额外块终止符 */
            } else {
                P_POS = save;
                node->c = parse_flow_body();
            }
        }
    }
    return node;
}

static void skip_type_flow(void) {
    skip_nl();
    if (cur()->kind == TK_IDENT || cur()->kind == TK_KEYWORD) adv();
    while (is_punct('[') || is_punct('(')) {
        char open = cur()->s[0];
        char close = open == '[' ? ']' : ')';
        int depth = 0;
        while (cur()->kind != TK_EOF) {
            if (is_punct(open)) depth++;
            else if (is_punct(close)) { depth--; adv(); if (depth == 0) break; continue; }
            adv();
        }
    }
}

static Node *parse_fn_flow(void) {
    Tok *t = cur();
    adv(); /* '\\' */
    Node *fn = node_new(ND_FN, t->line, t->col);
    fn->name = expect_ident("函数名");
    PtrVec names = {0}, defs = {0};
    while (cur()->kind == TK_IDENT) {
        Tok *p = cur();
        const char *name = (p->len == 1 && p->s[0] == '_') ? "_" : xstrndup(p->s, (size_t)p->len);
        adv();
        if (is_punct(':')) { adv(); skip_type_flow(); }
        pv_push(&names, (void *)name);
        pv_push(&defs, NULL);
    }
    if (is_kw("->")) { adv(); skip_type_flow(); }
    fn->nparams = names.len;
    fn->params = (Param *)xalloc(sizeof(Param) * (size_t)(names.len ? names.len : 1));
    for (int i = 0; i < names.len; i++) {
        fn->params[i].name = (const char *)names.items[i];
        fn->params[i].def = (Node *)defs.items[i];
        fn->params[i].is_mut = 0;
        fn->params[i].type = NULL;
    }
    free(names.items);
    free(defs.items);
    if (is_op("=")) {
        adv();
        skip_nl();
        fn->a = parse_expr(1);
    } else if (is_punct(':')) {
        Tok *et = cur();
        adv();
        skip_nl();
        Node *blk = node_new(ND_BLOCK, et->line, et->col);
        Node *st = parse_stmt(0);
        if (st) node_push(blk, st);
        fn->a = blk;
    } else {
        fn->a = parse_flow_body();
    }
    return fn;
}

static Node *parse_body(void) {
    skip_nl();
    if (g_flow) return parse_flow_body();
    if (is_punct('{')) return parse_block();
    if (is_punct(':')) {
        Tok *t = cur();
        adv();
        skip_nl();
        Node *blk = node_new(ND_BLOCK, t->line, t->col);
        Node *st = parse_stmt(0);
        if (st) node_push(blk, st);
        return blk;
    }
    return parse_block();
}

static Node *parse_primary(void) {
    skip_nl();
    Tok *t = cur();
    if (t->kind == TK_INT) {
        adv();
        Node *n = node_new(ND_LIT_INT, t->line, t->col);
        n->ival = t->i;
        return n;
    }
    if (t->kind == TK_FLOAT) {
        adv();
        Node *n = node_new(ND_LIT_FLOAT, t->line, t->col);
        n->fval = t->f;
        return n;
    }
    if (t->kind == TK_STR) {
        adv();
        Node *n = node_new(ND_LIT_STR, t->line, t->col);
        n->s = t->s;
        n->slen = t->len;
        return n;
    }
    if (t->kind == TK_FSTRING) {
        adv();
        return parse_fstring(t);
    }
    if (t->kind == TK_BYTES) {
        adv();
        Node *n = node_new(ND_LIT_BYTES, t->line, t->col);
        n->s = t->s;
        n->slen = t->len;
        return n;
    }
    if (t->kind == TK_IDENT) {
        const char *name = xstrndup(t->s, (size_t)t->len);
        adv();
        /* true / false 是 prelude 常量，不是关键字 */
        if (strcmp(name, "true") == 0 || strcmp(name, "false") == 0) {
            Node *n = node_new(ND_LIT_BOOL, t->line, t->col);
            n->bval = strcmp(name, "true") == 0;
            return n;
        }
        /* 点分名字：math.sqrt 等内建命名空间 */
        while (is_op(".") && peek(1)->kind == TK_IDENT) {
            adv();
            Tok *part = cur();
            name = xsprintf("%s.%s", name, xstrndup(part->s, (size_t)part->len));
            adv();
        }
        if (is_punct('(')) {
            Node *call = node_new(ND_CALL, t->line, t->col);
            Node *callee = node_new(ND_VAR, t->line, t->col);
            callee->name = name;
            call->a = callee;
            adv();
            skip_nl();
            if (!is_punct(')')) {
                for (;;) {
                    skip_nl();
                    node_push(call, parse_expr(1));
                    skip_nl();
                    if (is_punct(',')) { adv(); continue; }
                    break;
                }
            }
            skip_nl();
            expect_punct(')', "调用参数表");
            return call;
        }
        Node *v = node_new(ND_VAR, t->line, t->col);
        v->name = name;
        return v;
    }
    if (t->kind == TK_PUNCT) {
        char ch = t->s[0];
        if (ch == '(') {
            adv();
            Node *e = parse_expr(1);
            skip_nl();
            expect_punct(')', "括号");
            return e;
        }
        if (ch == '[') return parse_array_lit();
        if (ch == '{') return parse_brace_expr();
    }
    if (g_flow && t->kind == TK_OP && strcmp(t->s, "?") == 0) return parse_flow_if();
    if (t->kind == TK_KEYWORD) {
        if (strcmp(t->s, "if") == 0) return parse_if_expr();
        if (strcmp(t->s, "loop") == 0) {
            adv();
            Node *n = node_new(ND_LOOPEXPR, t->line, t->col);
            n->b = parse_block();
            return n;
        }
        if (strcmp(t->s, "true") == 0) { /* 不会出现：true 非关键字 */ }
    }
    reject_unsupported();
    ds_fail(t->line, t->col, "无法解析的表达式 '%.*s'", t->len, t->s);
    return NULL;
}

static Node *parse_postfix(void) {
    Node *e = parse_primary();
    for (;;) {
        if (!g_flow) skip_nl();
        if (is_punct('(')) {
            Tok *t = cur();
            adv();
            Node *call = node_new(ND_CALL, t->line, t->col);
            call->a = e;
            skip_nl();
            if (!is_punct(')')) {
                for (;;) {
                    skip_nl();
                    node_push(call, parse_expr(1));
                    skip_nl();
                    if (is_punct(',')) { adv(); continue; }
                    break;
                }
            }
            skip_nl();
            expect_punct(')', "调用参数表");
            e = call;
            continue;
        }
        if (is_punct('[')) {
            Tok *t = cur();
            adv();
            Node *idx = node_new(ND_INDEX, t->line, t->col);
            idx->a = e;
            idx->b = parse_expr(1);
            skip_nl();
            expect_punct(']', "下标");
            e = idx;
            continue;
        }
        break;
    }
    return e;
}

static Node *parse_unary(void) {
    skip_nl();
    if (cur()->kind == TK_OP) {
        const char *op = cur()->s;
        if (strcmp(op, "-") == 0 || strcmp(op, "!") == 0 || strcmp(op, "~") == 0 ||
            strcmp(op, "&") == 0 || strcmp(op, "*") == 0) {
            Tok *t = cur();
            adv();
            Node *n = node_new(ND_UNARY, t->line, t->col);
            n->name = op;
            n->a = parse_unary();
            return n;
        }
    }
    Node *e = parse_postfix();
    if (g_flow) {
        while (flow_atom_start()) {
            PtrVec args = {0};
            while (flow_atom_start()) pv_push(&args, parse_postfix());
            Node *call = node_new(ND_CALL, e->line, e->col);
            call->a = e;
            for (int i = 0; i < args.len; i++) node_push(call, (Node *)args.items[i]);
            free(args.items);
            e = call;
        }
    }
    return e;
}

static Node *parse_expr(int min_prec) {
    Node *left = parse_unary();
    for (;;) {
        Tok *t = cur();
        const char *op = NULL;
        if (t->kind == TK_OP) op = t->s;
        else if (t->kind == TK_KEYWORD && strcmp(t->s, "|>") == 0) op = t->s;
        if (!op) break;
        int pr = prec_of(op);
        if (pr == 0 || pr < min_prec) break;
        adv();
        Node *right = parse_expr(pr + 1);
        if (strcmp(op, "..") == 0) {
            Node *call = node_new(ND_CALL, t->line, t->col);
            call->a = make_var_node("range", t->line, t->col);
            node_push(call, left);
            node_push(call, right);
            left = call;
        } else {
            Node *b = node_new(ND_BINARY, t->line, t->col);
            b->name = op;
            b->a = left;
            b->b = right;
            left = b;
        }
    }
    return left;
}

static Node *parse_use(void) {
    Tok *t = cur();
    adv(); /* use */
    skip_nl();
    if (cur()->kind != TK_IDENT)
        ds_fail(cur()->line, cur()->col, "use 后需要模块名");
    Tok *p = cur();
    char *name = xstrndup(p->s, (size_t)p->len);
    adv();
    while (is_op(".") && peek(1)->kind == TK_IDENT) {
        adv();
        Tok *part = cur();
        name = xsprintf("%s.%s", name, xstrndup(part->s, (size_t)part->len));
        adv();
    }
    Node *n = node_new(ND_USE, t->line, t->col);
    n->name = name;
    skip_nl();
    if (is_kw("as")) {
        adv();
        skip_nl();
        if (cur()->kind != TK_IDENT)
            ds_fail(cur()->line, cur()->col, "as 后需要别名");
        Tok *a = cur();
        Node *alias = node_new(ND_LIT_STR, a->line, a->col);
        alias->s = xstrndup(a->s, (size_t)a->len);
        alias->slen = a->len;
        n->a = alias;
        adv();
    }
    return n;
}


static Node *make_noop_stmt(int line, int col) {
    Node *lit = node_new(ND_LIT_INT, line, col);
    lit->ival = 0;
    Node *st = node_new(ND_EXPRSTMT, line, col);
    st->a = lit;
    return st;
}

static Node *parse_static_binding(Tok *at) {
    /* Cut 形式：@static NAME: T = ADDR（没有 let/var 关键字） */
    skip_nl();
    const char *name = expect_ident("静态符号名");
    Node *n = node_new(ND_LET, at->line, at->col);
    n->name = name;
    n->bval = 0;
    skip_nl();
    if (is_punct(':')) { adv(); n->type_name = read_type_tag(); }
    skip_nl();
    if (is_op("=")) { adv(); n->a = parse_expr(1); }
    return n;
}

static Node *parse_at_item(void) {
    Tok *at = cur();
    adv(); /* @ */
    skip_nl();
    if (is_kw("irq")) {
        adv();
        if (is_punct('(')) {
            adv();
            int depth = 1;
            while (depth > 0 && cur()->kind != TK_EOF) {
                if (is_punct('(')) depth++;
                else if (is_punct(')')) depth--;
                adv();
            }
        }
        skip_nl();
        if (is_kw("irq")) adv();
        skip_nl();
        return parse_fn();
    }
    if (is_kw("static")) {
        adv();
        skip_nl();
        if (is_kw("var") || is_kw("let")) return parse_let(1);
        return parse_static_binding(at);
    }
    if (is_kw("asm")) {
        adv();
        skip_nl();
        if (cur()->kind == TK_STR) adv();
        else if (is_punct('(')) {
            int depth = 1;
            adv();
            while (depth > 0 && cur()->kind != TK_EOF) {
                if (is_punct('(')) depth++;
                else if (is_punct(')')) depth--;
                adv();
            }
        }
        return make_noop_stmt(at->line, at->col);
    }
    if (is_kw("unsafe")) {
        adv();
        skip_nl();
        if (is_punct('{')) return parse_block();
        return parse_stmt(0);
    }
    ds_fail(at->line, at->col, "未知 @ 属性");
    return NULL;
}

static Node *parse_program(int repl_mode) {
    P_POS = 0;
    Node *prog = node_new(ND_PROGRAM, 1, 1);
    skip_nl();
    if (is_kw("package")) {
        adv();
        skip_nl();
        if (cur()->kind == TK_IDENT) prog->name = expect_ident("包名");
        skip_nl();
    }
    for (;;) {
        skip_nl();
        while (is_punct(';')) { adv(); skip_nl(); }
        if (cur()->kind == TK_EOF) break;
        if (is_kw("package")) {
            adv();
            skip_nl();
            if (cur()->kind == TK_IDENT) { adv(); }
            continue;
        }
        /* 可见性修饰符：C 驱动不区分可见性，跳过 pub/priv/prot */
        while (is_kw("pub") || is_kw("priv") || is_kw("prot")) {
            adv();
            skip_nl();
        }
        Node *item = NULL;
        if (g_flow && cur()->kind == TK_OP && strcmp(cur()->s, "\\") == 0) item = parse_fn_flow();
        else if (is_kw("@")) item = parse_at_item();
        else if (is_kw("use")) item = parse_use();
        else if (is_kw("fn")) item = parse_fn();
        else if (is_kw("let") || is_kw("var")) item = parse_let(1);
        else item = parse_stmt(0);   /* 隐式入口：顶层语句 */
        if (item) node_push(prog, item);
        skip_nl();
    }
    return prog;
}

/* ------------------------------------------------------------------ */
/* 运行时：值 / 环境 / 求值                                            */
/* ------------------------------------------------------------------ */
enum {
    VL_UNIT, VL_BOOL, VL_INT, VL_FLOAT, VL_STR, VL_BYTES,
    VL_ARRAY, VL_MAP, VL_FUNC, VL_NATIVE
};

typedef struct Value Value;
typedef struct Env Env;

typedef struct UserFn {
    const char *name;
    Param *params;
    int nparams;
    Node *body;
    Env *closure;
} UserFn;

typedef Value *(*NativeFn)(Value **args, int nargs);

struct Value {
    int kind;
    int bval;
    int64_t ival;
    double fval;
    const char *s;
    int slen;
    Value **items;
    int nitems;
    Value **keys;
    Value **vals;
    int nkeys;
    UserFn *fn;
    NativeFn native;
};

typedef struct Bind {
    const char *name;
    Value *val;
    int is_mut;
    struct Bind *next;
} Bind;

struct Env {
    Env *parent;
    Bind *binds;
};

static Env *g_global;
static Value *g_ret;
static Value *g_breakval;

static Value *v_unit(void) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_UNIT;
    return v;
}
static Value *v_bool(int b) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_BOOL;
    v->bval = b ? 1 : 0;
    return v;
}
static Value *v_int(int64_t i) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_INT;
    v->ival = i;
    return v;
}
static Value *v_float(double f) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_FLOAT;
    v->fval = f;
    return v;
}
static Value *v_strn(const char *s, int len) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_STR;
    v->s = xstrndup(s, (size_t)len);
    v->slen = len;
    return v;
}
static Value *v_str(const char *s) { return v_strn(s, (int)strlen(s)); }
static Value *v_bytes(const char *s, int len) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_BYTES;
    v->s = xstrndup(s, (size_t)len);
    v->slen = len;
    return v;
}
static Value *v_array(void) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_ARRAY;
    return v;
}
static void v_array_push(Value *arr, Value *item) {
    arr->items = (Value **)realloc(arr->items, sizeof(Value *) * (size_t)(arr->nitems + 1));
    if (!arr->items) { fprintf(stderr, "ds: out of memory\n"); exit(3); }
    arr->items[arr->nitems++] = item;
}
static Value *v_map(void) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_MAP;
    return v;
}
static Value *v_func(Node *fn, Env *closure, const char *name) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_FUNC;
    v->fn = (UserFn *)xalloc(sizeof(UserFn));
    v->fn->name = name;
    v->fn->params = fn->params;
    v->fn->nparams = fn->nparams;
    v->fn->body = fn->a;
    v->fn->closure = closure;
    return v;
}
static Value *v_native(const char *name, NativeFn fn) {
    Value *v = (Value *)xalloc(sizeof(Value));
    memset(v, 0, sizeof *v);
    v->kind = VL_NATIVE;
    v->native = fn;
    v->s = name;
    return v;
}

/* ---------------- 字符串构建器（to_str 用） ---------------- */
typedef struct {
    char *buf;
    int len, cap;
} SB;

static void sb_init(SB *sb) {
    sb->cap = 64;
    sb->len = 0;
    sb->buf = (char *)malloc((size_t)sb->cap);
    sb->buf[0] = '\0';
}
static void sb_putc(SB *sb, char c) {
    if (sb->len + 2 > sb->cap) {
        sb->cap *= 2;
        sb->buf = (char *)realloc(sb->buf, (size_t)sb->cap);
    }
    sb->buf[sb->len++] = c;
    sb->buf[sb->len] = '\0';
}
static void sb_puts(SB *sb, const char *s) { while (*s) sb_putc(sb, *s++); }
static void sb_putn(SB *sb, const char *s, int n) { for (int i = 0; i < n; i++) sb_putc(sb, s[i]); }
static char *sb_finish(SB *sb) {
    char *out = xstrndup(sb->buf, (size_t)sb->len);
    free(sb->buf);
    return out;
}

static const char *v_repr(Value *v) {
    switch (v->kind) {
        case VL_UNIT: return "";
        case VL_BOOL: return v->bval ? "true" : "false";
        case VL_INT: return xsprintf("%lld", (long long)v->ival);
        case VL_FLOAT: {
            double f = v->fval;
            if (f == (double)(int64_t)f && fabs(f) < 1e16)
                return xsprintf("%.1f", f);
            return xsprintf("%g", f);
        }
        case VL_STR:
        case VL_BYTES: return v->s;
        case VL_ARRAY: {
            SB sb;
            sb_init(&sb);
            sb_putc(&sb, '[');
            for (int i = 0; i < v->nitems; i++) {
                if (i) sb_putc(&sb, ' ');
                sb_puts(&sb, v_repr(v->items[i]));
            }
            sb_putc(&sb, ']');
            return sb_finish(&sb);
        }
        case VL_MAP: {
            SB sb;
            sb_init(&sb);
            sb_putc(&sb, '{');
            for (int i = 0; i < v->nkeys; i++) {
                if (i) sb_puts(&sb, ", ");
                sb_puts(&sb, v_repr(v->keys[i]));
                sb_puts(&sb, ": ");
                sb_puts(&sb, v_repr(v->vals[i]));
            }
            sb_putc(&sb, '}');
            return sb_finish(&sb);
        }
        case VL_FUNC: return xsprintf("<fn %s>", v->fn->name ? v->fn->name : "anonymous");
        case VL_NATIVE: return xsprintf("<native fn %s>", v->s ? v->s : "?");
        default: return "?";
    }
}

/* ---------------- 相等 ---------------- */
static int v_equal(Value *a, Value *b) {
    if (a->kind != b->kind) {
        if ((a->kind == VL_INT && b->kind == VL_FLOAT) || (a->kind == VL_FLOAT && b->kind == VL_INT)) {
            double x = a->kind == VL_INT ? (double)a->ival : a->fval;
            double y = b->kind == VL_INT ? (double)b->ival : b->fval;
            return x == y;
        }
        return 0;
    }
    switch (a->kind) {
        case VL_UNIT: return 1;
        case VL_BOOL: return a->bval == b->bval;
        case VL_INT: return a->ival == b->ival;
        case VL_FLOAT: return a->fval == b->fval;
        case VL_STR:
        case VL_BYTES: return a->slen == b->slen && memcmp(a->s, b->s, (size_t)a->slen) == 0;
        case VL_ARRAY:
            if (a->nitems != b->nitems) return 0;
            for (int i = 0; i < a->nitems; i++)
                if (!v_equal(a->items[i], b->items[i])) return 0;
            return 1;
        case VL_MAP: {
            if (a->nkeys != b->nkeys) return 0;
            for (int i = 0; i < a->nkeys; i++) {
                Value *found = NULL;
                for (int j = 0; j < b->nkeys; j++)
                    if (v_equal(a->keys[i], b->keys[j])) { found = b->vals[j]; break; }
                if (!found || !v_equal(a->vals[i], found)) return 0;
            }
            return 1;
        }
        default: return a == b;
    }
}

/* ---------------- 环境 ---------------- */
static Env *env_new(Env *parent) {
    Env *e = (Env *)xalloc(sizeof(Env));
    e->parent = parent;
    e->binds = NULL;
    return e;
}
static Bind *env_find(Env *env, const char *name) {
    for (Env *e = env; e; e = e->parent)
        for (Bind *b = e->binds; b; b = b->next)
            if (strcmp(b->name, name) == 0) return b;
    return NULL;
}
static Value *env_get(Env *env, const char *name, int line, int col) {
    Bind *b = env_find(env, name);
    if (!b) ds_fail(line, col, "未定义的名字 `%s`", name);
    return b->val;
}
static void env_def(Env *env, const char *name, Value *val, int is_mut) {
    Bind *b = env_find(env, name);
    if (!b) {
        b = (Bind *)xalloc(sizeof(Bind));
        b->name = name;
        b->next = env->binds;
        env->binds = b;
    }
    b->val = val;
    b->is_mut = is_mut;
}
static void env_assign(Env *env, const char *name, Value *val, int line, int col) {
    Bind *b = env_find(env, name);
    if (!b) ds_fail(line, col, "未定义的名字 `%s`", name);
    if (!b->is_mut) ds_fail(line, col, "`%s` 不可变，不能赋值（用 var 声明）", name);
    b->val = val;
}

/* ---------------- 前向声明 ---------------- */
typedef enum { FLOW_NORMAL, FLOW_BREAK, FLOW_CONTINUE, FLOW_RETURN } Flow;

/* eval 内部（if 表达式/块表达式/loop 表达式）产生的控制流，由外层语句消费 */
static Flow g_pending = FLOW_NORMAL;

static Flow take_pending(void) {
    Flow f = g_pending;
    g_pending = FLOW_NORMAL;
    return f;
}

static Value *eval(Env *env, Node *n);
static Flow exec_block(Env *env, Node *block, Value **out_last);
static Flow exec_stmt(Env *env, Node *n, Value **out_last);
static Value *call_value(Value *callee, Value **args, int nargs, int line, int col);
static void register_builtins(void);

/* ------------------------------------------------------------------ */
/* 内建函数                                                           */
/* ------------------------------------------------------------------ */
static Value *nat_println(Value **args, int n) {
    for (int i = 0; i < n; i++) {
        if (i) fputc(' ', stdout);
        fputs(v_repr(args[i]), stdout);
    }
    fputc('\n', stdout);
    fflush(stdout);
    return v_unit();
}
static Value *nat_print(Value **args, int n) {
    for (int i = 0; i < n; i++) fputs(v_repr(args[i]), stdout);
    fflush(stdout);
    return v_unit();
}
static Value *nat_len(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "len 需要 1 个参数");
    Value *v = args[0];
    if (v->kind == VL_ARRAY) return v_int(v->nitems);
    if (v->kind == VL_STR || v->kind == VL_BYTES) return v_int(v->slen);
    if (v->kind == VL_MAP) return v_int(v->nkeys);
    ds_fail(0, 0, "len 不支持 %s", v_repr(v));
    return v_unit();
}
static Value *nat_range(Value **args, int n) {
    if (n < 1 || n > 2) ds_fail(0, 0, "range 需要 1~2 个参数");
    int64_t lo = 0, hi = 0;
    if (n == 1) hi = args[0]->ival;
    else { lo = args[0]->ival; hi = args[1]->ival; }
    Value *arr = v_array();
    for (int64_t i = lo; i < hi; i++) v_array_push(arr, v_int(i));
    return arr;
}
static Value *nat_str(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "str 需要 1 个参数");
    return v_str(v_repr(args[0]));
}
static Value *nat_concat(Value **args, int n) {
    if (n != 2) ds_fail(0, 0, "concat 需要 2 个参数");
    Value *a = args[0], *b = args[1];
    if (a->kind == VL_STR && b->kind == VL_STR) {
        SB sb;
        sb_init(&sb);
        sb_putn(&sb, a->s, a->slen);
        sb_putn(&sb, b->s, b->slen);
        return v_str(sb_finish(&sb));
    }
    if (a->kind == VL_ARRAY && b->kind == VL_ARRAY) {
        Value *arr = v_array();
        for (int i = 0; i < a->nitems; i++) v_array_push(arr, a->items[i]);
        for (int i = 0; i < b->nitems; i++) v_array_push(arr, b->items[i]);
        return arr;
    }
    ds_fail(0, 0, "concat 需要两个 str 或两个数组");
    return v_unit();
}
static Value *nat_format(Value **args, int n) {
    if (n == 0) return v_str("");
    Value *first = args[0];
    if (first->kind == VL_STR && n > 1) {
        SB sb;
        sb_init(&sb);
        int argi = 1;
        for (int i = 0; i < first->slen; i++) {
            if (first->s[i] == '{' && i + 1 < first->slen && first->s[i + 1] == '}' && argi < n) {
                sb_puts(&sb, v_repr(args[argi++]));
                i++;
            } else {
                sb_putc(&sb, first->s[i]);
            }
        }
        return v_str(sb_finish(&sb));
    }
    SB sb;
    sb_init(&sb);
    for (int i = 0; i < n; i++) sb_puts(&sb, v_repr(args[i]));
    return v_str(sb_finish(&sb));
}
static Value *nat_sqrt(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "math.sqrt 需要 1 个参数");
    double x = args[0]->kind == VL_INT ? (double)args[0]->ival : args[0]->fval;
    return v_float(sqrt(x));
}
static Value *nat_round(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "math.round 需要 1 个参数");
    double x = args[0]->kind == VL_INT ? (double)args[0]->ival : args[0]->fval;
    return v_float(round(x));
}
static Value *nat_floor(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "math.floor 需要 1 个参数");
    double x = args[0]->kind == VL_INT ? (double)args[0]->ival : args[0]->fval;
    return v_float(floor(x));
}
static Value *nat_ceil(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "math.ceil 需要 1 个参数");
    double x = args[0]->kind == VL_INT ? (double)args[0]->ival : args[0]->fval;
    return v_float(ceil(x));
}
static Value *nat_abs(Value **args, int n) {
    if (n != 1) ds_fail(0, 0, "abs 需要 1 个参数");
    if (args[0]->kind == VL_INT) return v_int(args[0]->ival < 0 ? -args[0]->ival : args[0]->ival);
    return v_float(fabs(args[0]->fval));
}
static Value *nat_pow(Value **args, int n) {
    if (n != 2) ds_fail(0, 0, "pow 需要 2 个参数");
    double x = args[0]->kind == VL_INT ? (double)args[0]->ival : args[0]->fval;
    double y = args[1]->kind == VL_INT ? (double)args[1]->ival : args[1]->fval;
    return v_float(pow(x, y));
}

static void define_builtin(const char *name, NativeFn fn) {
    env_def(g_global, name, v_native(name, fn), 0);
}

static void register_builtins(void) {
    define_builtin("println", nat_println);
    define_builtin("print", nat_print);
    define_builtin("len", nat_len);
    define_builtin("range", nat_range);
    define_builtin("str", nat_str);
    define_builtin("concat", nat_concat);
    define_builtin("format", nat_format);
    define_builtin("p", nat_println);
    define_builtin("s", nat_str);
    define_builtin("l", nat_len);
    define_builtin("r", nat_range);
    define_builtin("math.sqrt", nat_sqrt);
    define_builtin("math.round", nat_round);
    define_builtin("math.floor", nat_floor);
    define_builtin("math.ceil", nat_ceil);
    define_builtin("math.abs", nat_abs);
    define_builtin("math.pow", nat_pow);
    define_builtin("abs", nat_abs);
    define_builtin("pow", nat_pow);
}

/* ------------------------------------------------------------------ */
/* 求值                                                               */
/* ------------------------------------------------------------------ */
static int require_bool(Value *v, int line, int col, const char *what) {
    if (v->kind != VL_BOOL) ds_fail(line, col, "%s 需要 bool，实际是 %s", what, v_repr(v));
    return v->bval;
}

static Value *binop(const char *op, Value *a, Value *b, int line, int col) {
    if (strcmp(op, "==") == 0) return v_bool(v_equal(a, b));
    if (strcmp(op, "!=") == 0) return v_bool(!v_equal(a, b));

    if (strcmp(op, "+") == 0) {
        if (a->kind == VL_INT && b->kind == VL_INT) return v_int(a->ival + b->ival);
        if (a->kind == VL_FLOAT && b->kind == VL_FLOAT) return v_float(a->fval + b->fval);
        if (a->kind == VL_STR && b->kind == VL_STR) {
            SB sb;
            sb_init(&sb);
            sb_putn(&sb, a->s, a->slen);
            sb_putn(&sb, b->s, b->slen);
            return v_str(sb_finish(&sb));
        }
        if (a->kind == VL_ARRAY && b->kind == VL_ARRAY) {
            Value *arr = v_array();
            for (int i = 0; i < a->nitems; i++) v_array_push(arr, a->items[i]);
            for (int i = 0; i < b->nitems; i++) v_array_push(arr, b->items[i]);
            return arr;
        }
        ds_fail(line, col, "`+` 类型不匹配：%s 与 %s", v_repr(a), v_repr(b));
    }
    if (strcmp(op, "-") == 0) {
        if (a->kind == VL_INT && b->kind == VL_INT) return v_int(a->ival - b->ival);
        if (a->kind == VL_FLOAT && b->kind == VL_FLOAT) return v_float(a->fval - b->fval);
        ds_fail(line, col, "`-` 类型不匹配");
    }
    if (strcmp(op, "*") == 0) {
        if (a->kind == VL_INT && b->kind == VL_INT) return v_int(a->ival * b->ival);
        if (a->kind == VL_FLOAT && b->kind == VL_FLOAT) return v_float(a->fval * b->fval);
        ds_fail(line, col, "`*` 类型不匹配");
    }
    if (strcmp(op, "/") == 0) {
        if (a->kind == VL_INT && b->kind == VL_INT) {
            if (b->ival == 0) ds_fail(line, col, "除数为 0");
            int64_t q = a->ival / b->ival;
            if ((a->ival % b->ival != 0) && ((a->ival < 0) != (b->ival < 0))) q--;
            return v_int(q);
        }
        if (a->kind == VL_FLOAT && b->kind == VL_FLOAT) {
            if (b->fval == 0.0) ds_fail(line, col, "除数为 0");
            return v_float(a->fval / b->fval);
        }
        ds_fail(line, col, "`/` 类型不匹配");
    }
    if (strcmp(op, "%") == 0) {
        if (a->kind == VL_INT && b->kind == VL_INT) {
            if (b->ival == 0) ds_fail(line, col, "除数为 0");
            return v_int(a->ival % b->ival);
        }
        ds_fail(line, col, "`%%` 需要两个整数");
    }
    if (strcmp(op, "&") == 0 || strcmp(op, "|") == 0 || strcmp(op, "^") == 0 ||
        strcmp(op, "<<") == 0 || strcmp(op, ">>") == 0) {
        if (a->kind != VL_INT || b->kind != VL_INT) ds_fail(line, col, "位运算需要两个整数");
        if (strcmp(op, "&") == 0) return v_int(a->ival & b->ival);
        if (strcmp(op, "|") == 0) return v_int(a->ival | b->ival);
        if (strcmp(op, "^") == 0) return v_int(a->ival ^ b->ival);
        if (b->ival < 0 || b->ival >= 64) ds_fail(line, col, "移位量越界");
        return v_int(strcmp(op, "<<") == 0 ? (a->ival << b->ival) : (a->ival >> b->ival));
    }
    if (strcmp(op, "<") == 0 || strcmp(op, ">") == 0 || strcmp(op, "<=") == 0 || strcmp(op, ">=") == 0) {
        int cmp_result = 0;
        if (a->kind == VL_INT && b->kind == VL_INT) cmp_result = (a->ival > b->ival) - (a->ival < b->ival);
        else if (a->kind == VL_FLOAT && b->kind == VL_FLOAT) cmp_result = (a->fval > b->fval) - (a->fval < b->fval);
        else if (a->kind == VL_STR && b->kind == VL_STR) {
            int m = memcmp(a->s, b->s, (size_t)(a->slen < b->slen ? a->slen : b->slen));
            cmp_result = m != 0 ? (m > 0 ? 1 : -1) : (a->slen > b->slen) - (a->slen < b->slen);
        } else {
            ds_fail(line, col, "不可比较：%s 与 %s", v_repr(a), v_repr(b));
        }
        if (strcmp(op, "<") == 0) return v_bool(cmp_result < 0);
        if (strcmp(op, ">") == 0) return v_bool(cmp_result > 0);
        if (strcmp(op, "<=") == 0) return v_bool(cmp_result <= 0);
        return v_bool(cmp_result >= 0);
    }
    ds_fail(line, col, "未知二元运算符 `%s`", op);
    return v_unit();
}

static Value *map_get(Value *map, Value *key, int line, int col) {
    for (int i = 0; i < map->nkeys; i++)
        if (v_equal(map->keys[i], key)) return map->vals[i];
    ds_fail(line, col, "映射中没有键 %s", v_repr(key));
    return v_unit();
}
static void map_set(Value *map, Value *key, Value *val) {
    for (int i = 0; i < map->nkeys; i++)
        if (v_equal(map->keys[i], key)) { map->vals[i] = val; return; }
    map->keys = (Value **)realloc(map->keys, sizeof(Value *) * (size_t)(map->nkeys + 1));
    map->vals = (Value **)realloc(map->vals, sizeof(Value *) * (size_t)(map->nkeys + 1));
    if (!map->keys || !map->vals) { fprintf(stderr, "ds: out of memory\n"); exit(3); }
    map->keys[map->nkeys] = key;
    map->vals[map->nkeys] = val;
    map->nkeys++;
}

static int64_t index_int(Value *v, int line, int col) {
    if (v->kind != VL_INT) ds_fail(line, col, "下标需要整数");
    return v->ival;
}

static Value *eval_pipe(Env *env, Node *n) {
    Value *left = eval(env, n->a);
    if (n->b->kind == ND_CALL) {
        Value *callee = eval(env, n->b->a);
        int nargs = n->b->nitems;
        Value **args = (Value **)xalloc(sizeof(Value *) * (size_t)(nargs + 1));
        args[0] = left;
        for (int i = 0; i < nargs; i++) args[i + 1] = eval(env, n->b->items[i]);
        return call_value(callee, args, nargs + 1, n->line, n->col);
    }
    Value *callee = eval(env, n->b);
    Value *args[1] = {left};
    return call_value(callee, args, 1, n->line, n->col);
}

static Value *eval(Env *env, Node *n) {
    switch (n->kind) {
        case ND_LIT_INT: return v_int(n->ival);
        case ND_LIT_FLOAT: return v_float(n->fval);
        case ND_LIT_STR: return v_strn(n->s, n->slen);
        case ND_LIT_BYTES: return v_bytes(n->s, n->slen);
        case ND_LIT_BOOL: return v_bool(n->bval);
        case ND_VAR: {
            if (strcmp(n->name, "_") == 0) ds_fail(n->line, n->col, "`_` 不能在表达式中读取");
            return env_get(env, n->name, n->line, n->col);
        }
        case ND_ARRAY: {
            Value *arr = v_array();
            for (int i = 0; i < n->nitems; i++) v_array_push(arr, eval(env, n->items[i]));
            return arr;
        }
        case ND_MAP: {
            Value *map = v_map();
            for (int i = 0; i < n->nkeys; i++)
                map_set(map, eval(env, n->keys[i]), eval(env, n->items[i]));
            return map;
        }
        case ND_UNARY: {
            const char *op = n->name;
            if (strcmp(op, "&") == 0 || strcmp(op, "*") == 0)
                ds_fail(n->line, n->col, "C 驱动 v0.1 不支持指针/解引用（Python 参考实现支持）");
            Value *v = eval(env, n->a);
            if (strcmp(op, "-") == 0) {
                if (v->kind == VL_INT) return v_int(-v->ival);
                if (v->kind == VL_FLOAT) return v_float(-v->fval);
                ds_fail(n->line, n->col, "一元 `-` 需要数值");
            }
            if (strcmp(op, "!") == 0) return v_bool(!require_bool(v, n->line, n->col, "`!`"));
            if (strcmp(op, "~") == 0) {
                if (v->kind != VL_INT) ds_fail(n->line, n->col, "`~` 需要整数");
                return v_int(~v->ival);
            }
            ds_fail(n->line, n->col, "未知一元运算符 `%s`", op);
            return v_unit();
        }
        case ND_BINARY: {
            const char *op = n->name;
            if (strcmp(op, "&&") == 0) {
                int l = require_bool(eval(env, n->a), n->line, n->col, "`&&`");
                if (!l) return v_bool(0);
                return v_bool(require_bool(eval(env, n->b), n->line, n->col, "`&&`"));
            }
            if (strcmp(op, "||") == 0) {
                int l = require_bool(eval(env, n->a), n->line, n->col, "`||`");
                if (l) return v_bool(1);
                return v_bool(require_bool(eval(env, n->b), n->line, n->col, "`||`"));
            }
            if (strcmp(op, "|>") == 0) return eval_pipe(env, n);
            Value *a = eval(env, n->a);
            Value *b = eval(env, n->b);
            return binop(op, a, b, n->line, n->col);
        }
        case ND_CALL: {
            Value *callee = eval(env, n->a);
            int nargs = n->nitems;
            Value **args = nargs ? (Value **)xalloc(sizeof(Value *) * (size_t)nargs) : NULL;
            for (int i = 0; i < nargs; i++) args[i] = eval(env, n->items[i]);
            return call_value(callee, args, nargs, n->line, n->col);
        }
        case ND_INDEX: {
            Value *obj = eval(env, n->a);
            Value *idx = eval(env, n->b);
            if (obj->kind == VL_ARRAY) {
                int64_t i = index_int(idx, n->line, n->col);
                if (i < 0) i += obj->nitems;
                if (i < 0 || i >= obj->nitems) ds_fail(n->line, n->col, "数组下标越界：%lld", (long long)i);
                return obj->items[i];
            }
            if (obj->kind == VL_STR || obj->kind == VL_BYTES) {
                int64_t i = index_int(idx, n->line, n->col);
                if (i < 0) i += obj->slen;
                if (i < 0 || i >= obj->slen) ds_fail(n->line, n->col, "字符串下标越界");
                return v_strn(obj->s + i, 1);
            }
            if (obj->kind == VL_MAP) return map_get(obj, idx, n->line, n->col);
            ds_fail(n->line, n->col, "值不可索引：%s", v_repr(obj));
            return v_unit();
        }
        case ND_IFEXPR: {
            int cond = require_bool(eval(env, n->a), n->line, n->col, "if 条件");
            Value *last = v_unit();
            Flow f = FLOW_NORMAL;
            if (cond) {
                f = exec_block(env, n->b, &last);
            } else if (n->c) {
                if (n->c->kind == ND_BLOCK) f = exec_block(env, n->c, &last);
                else {
                    Value *v = eval(env, n->c);
                    if (g_pending != FLOW_NORMAL) { f = take_pending(); }
                    else return v;
                }
            }
            if (f != FLOW_NORMAL) { g_pending = f; return v_unit(); }
            return last;
        }
        case ND_BLOCKEXPR: {
            Value *last = v_unit();
            Flow f = exec_block(env, n->b, &last);
            if (f != FLOW_NORMAL) { g_pending = f; return v_unit(); }
            return last;
        }
        case ND_LOOPEXPR: {
            for (;;) {
                Value *last = v_unit();
                Flow f = exec_block(env, n->b, &last);
                if (f == FLOW_BREAK) return g_breakval;
                if (f == FLOW_CONTINUE) continue;
                if (f == FLOW_RETURN) { g_pending = FLOW_RETURN; return v_unit(); }
                if (f != FLOW_NORMAL) { g_pending = f; return v_unit(); }
            }
        }
        default:
            ds_fail(n->line, n->col, "无法求值的节点（kind=%d）", n->kind);
            return v_unit();
    }
}

/* ------------------------------------------------------------------ */
/* 语句执行                                                           */
/* ------------------------------------------------------------------ */
static Flow exec_stmt(Env *env, Node *n, Value **out_last) {
    switch (n->kind) {
        case ND_LET: {
            Value *val = n->a ? eval(env, n->a) : v_unit();
            { Flow f = take_pending(); if (f != FLOW_NORMAL) { *out_last = v_unit(); return f; } }
            env_def(env, n->name, val, n->bval);
            *out_last = v_unit();
            return FLOW_NORMAL;
        }
        case ND_ASSIGN: {
            Node *target = n->a;
            Value *val = eval(env, n->b);
            { Flow f = take_pending(); if (f != FLOW_NORMAL) { *out_last = v_unit(); return f; } }
            if (n->name && strcmp(n->name, "=") != 0) {
                char base[8];
                size_t bl = strlen(n->name);
                if (bl >= sizeof base) bl = sizeof base - 1;
                memcpy(base, n->name, bl);
                base[bl - 1] = '\0';
                Value *cur = eval(env, target);
                { Flow f = take_pending(); if (f != FLOW_NORMAL) { *out_last = v_unit(); return f; } }
                val = binop(base, cur, val, n->line, n->col);
            }
            if (target->kind == ND_VAR) {
                if (strcmp(target->name, "_") == 0) { *out_last = val; return FLOW_NORMAL; }
                if (env_find(env, target->name) == NULL)
                    env_def(env, target->name, val, 0);   /* 精简写法：首次赋值即不可变定义 */
                else
                    env_assign(env, target->name, val, n->line, n->col);
            } else {
                Value *obj = eval(env, target->a);
                Value *idx = eval(env, target->b);
                if (obj->kind == VL_ARRAY) {
                    int64_t i = index_int(idx, n->line, n->col);
                    if (i < 0) i += obj->nitems;
                    if (i < 0 || i >= obj->nitems) ds_fail(n->line, n->col, "数组下标越界");
                    obj->items[i] = val;
                } else if (obj->kind == VL_MAP) {
                    map_set(obj, idx, val);
                } else {
                    ds_fail(n->line, n->col, "不可下标赋值：%s", v_repr(obj));
                }
            }
            *out_last = v_unit();
            return FLOW_NORMAL;
        }
        case ND_EXPRSTMT: {
            Value *v = eval(env, n->a);
            { Flow f = take_pending(); if (f != FLOW_NORMAL) { *out_last = v_unit(); return f; } }
            *out_last = v;
            return FLOW_NORMAL;
        }
        case ND_IFEXPR: {
            Value *v = eval(env, n);
            { Flow f = take_pending(); if (f != FLOW_NORMAL) { *out_last = v_unit(); return f; } }
            *out_last = v;
            return FLOW_NORMAL;
        }
        case ND_BLOCK:
            return exec_block(env, n, out_last);
        case ND_WHILE: {
            for (;;) {
                Value *cond = eval(env, n->a);
                { Flow pf = take_pending(); if (pf != FLOW_NORMAL) { *out_last = v_unit(); return pf; } }
                if (!require_bool(cond, n->line, n->col, "while 条件")) break;
                Value *last = v_unit();
                Flow f = exec_block(env, n->b, &last);
                if (f == FLOW_BREAK) break;
                if (f == FLOW_RETURN) return f;
                if (f == FLOW_CONTINUE) continue;
            }
            *out_last = v_unit();
            return FLOW_NORMAL;
        }
        case ND_LOOP: {
            for (;;) {
                Value *last = v_unit();
                Flow f = exec_block(env, n->b, &last);
                if (f == FLOW_BREAK) break;
                if (f == FLOW_RETURN) return f;
                if (f == FLOW_CONTINUE) continue;
            }
            *out_last = v_unit();
            return FLOW_NORMAL;
        }
        case ND_LOOPEXPR: {
            *out_last = eval(env, n);
            return FLOW_NORMAL;
        }
        case ND_FOR: {
            Value *iterable = eval(env, n->a);
            { Flow pf = take_pending(); if (pf != FLOW_NORMAL) { *out_last = v_unit(); return pf; } }
            int64_t idx = 0;
            for (;;) {
                Value *item = NULL;
                if (iterable->kind == VL_ARRAY) {
                    if (idx >= iterable->nitems) break;
                    item = iterable->items[idx];
                } else if (iterable->kind == VL_STR || iterable->kind == VL_BYTES) {
                    if (idx >= iterable->slen) break;
                    item = v_strn(iterable->s + idx, 1);
                } else if (iterable->kind == VL_MAP) {
                    if (idx >= iterable->nkeys) break;
                    item = iterable->keys[idx];
                } else {
                    ds_fail(n->line, n->col, "值不可迭代：%s", v_repr(iterable));
                }
                idx++;
                Env *iter_env = env_new(env);
                if (strcmp(n->name, "_") != 0) env_def(iter_env, n->name, item, 0);
                Value *last = v_unit();
                Flow f = exec_block(iter_env, n->b, &last);
                if (f == FLOW_BREAK) break;
                if (f == FLOW_RETURN) return f;
                if (f == FLOW_CONTINUE) continue;
            }
            *out_last = v_unit();
            return FLOW_NORMAL;
        }
        case ND_BREAK:
            g_breakval = n->a ? eval(env, n->a) : v_unit();
            (void)take_pending();
            *out_last = v_unit();
            return FLOW_BREAK;
        case ND_CONTINUE:
            *out_last = v_unit();
            return FLOW_CONTINUE;
        case ND_RETURN:
            g_ret = n->a ? eval(env, n->a) : v_unit();
            (void)take_pending();
            *out_last = v_unit();
            return FLOW_RETURN;
        default: {
            Value *v = eval(env, n);
            { Flow f = take_pending(); if (f != FLOW_NORMAL) { *out_last = v_unit(); return f; } }
            *out_last = v;
            return FLOW_NORMAL;
        }
    }
}

static long g_steps = 0;
#define DS_MAX_STEPS 50000000L

static Flow exec_block(Env *parent, Node *block, Value **out_last) {
    if (++g_steps > DS_MAX_STEPS)
        ds_fail(block->line, block->col, "执行步数超过上限（可能是死循环）");
    Env *scope = env_new(parent);
    Value *last = v_unit();
    for (int i = 0; i < block->nitems; i++) {
        Value *item_val = v_unit();
        Flow f = exec_stmt(scope, block->items[i], &item_val);
        if (f != FLOW_NORMAL) {
            *out_last = last;
            return f;
        }
        last = item_val;
    }
    *out_last = last;
    return FLOW_NORMAL;
}

/* ------------------------------------------------------------------ */
/* 调用                                                               */
/* ------------------------------------------------------------------ */
static Value *call_value(Value *callee, Value **args, int nargs, int line, int col) {
    if (callee->kind == VL_NATIVE) return callee->native(args, nargs);
    if (callee->kind == VL_FUNC) {
        UserFn *f = callee->fn;
        if (nargs > f->nparams) ds_fail(line, col, "`%s` 实参过多（%d > %d）", f->name, nargs, f->nparams);
        Env *call_env = env_new(f->closure);
        for (int i = 0; i < f->nparams; i++) {
            Value *val = NULL;
            if (i < nargs) val = args[i];
            else if (f->params[i].def) val = eval(call_env, f->params[i].def);
            else ds_fail(line, col, "`%s` 缺少实参 `%s`", f->name, f->params[i].name);
            env_def(call_env, f->params[i].name, val, 0);
        }
        Value *last = v_unit();
        g_pending = FLOW_NORMAL;
        if (f->body && f->body->kind != ND_BLOCK) {
            /* 表达式函数体：fn f(x)=x+1 */
            Value *v = eval(call_env, f->body);
            (void)take_pending();
            return v;
        }
        Flow flow = exec_block(call_env, f->body, &last);
        if (flow == FLOW_RETURN) return g_ret;
        if (flow == FLOW_NORMAL) flow = take_pending();
        if (flow == FLOW_RETURN) return g_ret;
        if (flow != FLOW_NORMAL) ds_fail(line, col, "break/continue 不能跨函数");
        return last;
    }
    ds_fail(line, col, "不可调用：%s", v_repr(callee));
    return v_unit();
}

/* ------------------------------------------------------------------ */
/* 程序执行                                                           */
/* ------------------------------------------------------------------ */
static int g_had_top_stmts = 0;


/* ---------------- dspm 包解析（C 驱动） ---------------- */
static const char *dspm_home(void) {
    static char buf[4096];
    const char *e = getenv("DSPM_HOME");
    if (e && *e) {
        snprintf(buf, sizeof buf, "%s", e);
    } else {
        const char *h = getenv("HOME");
        snprintf(buf, sizeof buf, "%s/.ds", h ? h : ".");
    }
    size_t n = strlen(buf);
    while (n > 1 && buf[n - 1] == '/') buf[--n] = '\0';
    return buf;
}

static char *read_text_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long sz = ftell(f);
    if (sz < 0) { fclose(f); return NULL; }
    rewind(f);
    char *buf = (char *)xalloc((size_t)sz + 1);
    size_t got = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    buf[got] = '\0';
    return buf;
}

/* 极简 TOML 数组提取：key = ["a", "b"] */
static int toml_array(const char *text, const char *key, char out[][128], int cap) {
    const char *p = strstr(text, key);
    if (!p) return 0;
    p = strchr(p, '=');
    if (!p) return 0;
    p = strchr(p, '[');
    if (!p) return 0;
    p++;
    int n = 0;
    while (*p && *p != ']' && n < cap) {
        if (*p == '"') {
            p++;
            int len = 0;
            while (*p && *p != '"' && len < 127) {
                if (*p == '\\' && p[1]) p++;
                out[n][len++] = *p++;
            }
            out[n][len] = '\0';
            n++;
            if (*p == '"') p++;
        } else {
            p++;
        }
    }
    return n;
}

static int module_targets_ok(const char *toml) {
    char targets[32][128];
    int n = toml_array(toml, "targets", targets, 32);
    if (n == 0) return 1;   /* 未声明：默认 app */
    for (int i = 0; i < n; i++) {
        if (strcasecmp(targets[i], "ds") == 0 || strcasecmp(targets[i], "cut") == 0 ||
            strcasecmp(targets[i], "base") == 0 || strcasecmp(targets[i], "app") == 0 ||
            strcasecmp(targets[i], "bare") == 0)
            return 1;
    }
    return 0;
}

static int resolve_module_file(const char *module, char *out, size_t out_sz) {
    const char *mod = strrchr(module, '.');
    mod = mod ? mod + 1 : module;
    char pattern[4096];
    snprintf(pattern, sizeof pattern, "%s/pkg/*/*/ds.toml", dspm_home());
    glob_t g;
    memset(&g, 0, sizeof g);
    if (glob(pattern, 0, NULL, &g) != 0) return 0;
    int found = 0;
    for (size_t i = 0; i < g.gl_pathc && !found; i++) {
        char *toml = read_text_file(g.gl_pathv[i]);
        if (!toml) continue;
        char exports[64][128];
        int ne = toml_array(toml, "exports", exports, 64);
        int match = (ne == 0);
        for (int j = 0; j < ne; j++)
            if (strcasecmp(exports[j], mod) == 0) { match = 1; break; }
        if (!match || !module_targets_ok(toml)) { continue; }
        char pkgdir[4096];
        snprintf(pkgdir, sizeof pkgdir, "%s", g.gl_pathv[i]);
        char *slash = strrchr(pkgdir, '/');
        if (slash) *slash = '\0';
        const char *modname = (ne > 0 && strcasecmp(exports[0], mod) == 0) ? exports[0] : mod;
        static const char *fmts[] = {"%s/src/%s.ds", "%s/src/%s.dsf", "%s/%s.ds", NULL};
        for (int k = 0; fmts[k] && !found; k++) {
            char cand[4096];
            snprintf(cand, sizeof cand, fmts[k], pkgdir, modname);
            if (access(cand, R_OK) == 0) {
                snprintf(out, out_sz, "%s", cand);
                found = 1;
            }
        }
    }
    globfree(&g);
    return found;
}

static void load_module_file(const char *path, const char *ns) {
    if (getenv("DSPM_DEBUG")) fprintf(stderr, "[dspm] load %s as %s\n", path, ns);
    static char loaded[256][256];
    static int nloaded = 0;
    for (int i = 0; i < nloaded; i++)
        if (strcmp(loaded[i], ns) == 0) return;
    if (nloaded >= 256)
        ds_fail(1, 1, "模块加载层数超过上限");
    int save_flow = g_flow;
    Tok *save_toks = g_toks;
    int save_n = g_ntoks, save_cap = g_captoks, save_pos = P_POS;
    char *src = read_text_file(path);
    if (!src) ds_fail(1, 1, "无法读取模块：%s", path);
    setup_flow(path, src);
    g_ntoks = 0;       /* 关键：重置 token 计数，避免复用外层 token */
    lex_source(src);
    P_POS = 0;
    Node *prog = parse_program(0);
    if (getenv("DSPM_DEBUG")) fprintf(stderr, "[dspm] parsed %s items=%d\n", ns, prog->nitems);
    /* 模块内的 use 先加载 */
    for (int i = 0; i < prog->nitems; i++)
        if (prog->items[i]->kind == ND_USE) {
            Node *u = prog->items[i];
            char target[4096];
            if (!resolve_module_file(u->name, target, sizeof target))
                ds_fail(u->line, u->col,
                        "找不到模块 `%s`；请运行 `dspm install <user>/<repo>`（DSPM_HOME=%s）",
                        u->name, dspm_home());
            const char *child_ns = u->a ? u->a->s : u->name;
            const char *dot = strrchr(u->name, '.');
            if (!u->a && dot) child_ns = dot + 1;
            load_module_file(target, child_ns);
        }
    Env *mod_env = env_new(g_global);
    if (getenv("DSPM_DEBUG")) fprintf(stderr, "[dspm] mod_env %s\n", ns);
    for (int i = 0; i < prog->nitems; i++) {
        Node *fn = prog->items[i];
        if (fn->kind == ND_FN)
            env_def(mod_env, fn->name, v_func(fn, mod_env, fn->name), 0);
    }
    for (int i = 0; i < prog->nitems; i++) {
        Node *item = prog->items[i];
        if (item->kind == ND_LET) {
            Value *val = item->a ? eval(mod_env, item->a) : v_unit();
            env_def(mod_env, item->name, val, item->bval);
        }
    }
    for (int i = 0; i < prog->nitems; i++) {
        Node *fn = prog->items[i];
        if (fn->kind == ND_FN) {
            char *exposed = xsprintf("%s.%s", ns, fn->name);
            env_def(g_global, exposed, v_func(fn, mod_env, fn->name), 0);
        }
    }
    if (getenv("DSPM_DEBUG")) fprintf(stderr, "[dspm] exported %s\n", ns);
    snprintf(loaded[nloaded], sizeof loaded[nloaded], "%s", ns);
    nloaded++;
    g_flow = save_flow;
    g_toks = save_toks;
    g_ntoks = save_n;
    g_captoks = save_cap;
    P_POS = save_pos;
}

static void load_use_item(Node *item) {
    if (getenv("DSPM_DEBUG")) fprintf(stderr, "[dspm] use %s\n", item->name);
    char path[4096];
    if (!resolve_module_file(item->name, path, sizeof path))
        ds_fail(item->line, item->col,
                "找不到模块 `%s`；请运行 `dspm install <user>/<repo>`（DSPM_HOME=%s）",
                item->name, dspm_home());
    const char *ns = item->a ? item->a->s : item->name;
    const char *dot = strrchr(item->name, '.');
    if (!item->a && dot) ns = dot + 1;
    load_module_file(path, ns);
}

static void run_program(Node *prog, int repl_mode, Value **out_last) {
    Value *last = v_unit();
    g_had_top_stmts = 0;
    /* 先解析 use（dspm 包） */
    for (int i = 0; i < prog->nitems; i++)
        if (prog->items[i]->kind == ND_USE) load_use_item(prog->items[i]);
    /* 再注册所有函数（隐式入口允许函数在语句之后定义） */
    for (int i = 0; i < prog->nitems; i++) {
        Node *item = prog->items[i];
        if (item->kind == ND_FN)
            env_def(g_global, item->name, v_func(item, g_global, item->name), 0);
    }
    /* 再执行顶层 let（可引用已注册的函数） */
    for (int i = 0; i < prog->nitems; i++) {
        Node *item = prog->items[i];
        if (item->kind != ND_LET) continue;
        Value *val = item->a ? eval(g_global, item->a) : v_unit();
        env_def(g_global, item->name, val, item->bval);
    }
    /* 最后按顺序执行顶层语句 */
    for (int i = 0; i < prog->nitems; i++) {
        Node *item = prog->items[i];
        if (item->kind == ND_FN || item->kind == ND_LET || item->kind == ND_PACKAGE ||
            item->kind == ND_USE) continue;
        g_pending = FLOW_NORMAL;
        g_had_top_stmts = 1;
        Value *stmt_val = v_unit();
        Flow flow = exec_stmt(g_global, item, &stmt_val);
        if (flow == FLOW_NORMAL) flow = take_pending();
        if (flow == FLOW_BREAK || flow == FLOW_CONTINUE || flow == FLOW_RETURN) {
            if (repl_mode) ds_fail(item->line, item->col, "break/continue/return 不能在顶层使用");
            ds_fail(item->line, item->col, "控制流语句不能在顶层使用");
        }
        last = stmt_val;
    }
    *out_last = last;
}

static void run_main_if_present(void) {
    Bind *b = env_find(g_global, "main");
    if (b && b->val && b->val->kind == VL_FUNC) call_value(b->val, NULL, 0, 0, 0);
}

/* ------------------------------------------------------------------ */
/* 工具 / CLI / REPL                                                  */
/* ------------------------------------------------------------------ */
static const char *base_name(const char *path) {
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static char *read_file_text(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) ds_fail(0, 0, "找不到源文件：%s", path);
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); ds_fail(0, 0, "读取失败：%s", path); }
    long size = ftell(f);
    if (size < 0) { fclose(f); ds_fail(0, 0, "读取失败：%s", path); }
    rewind(f);
    char *buf = (char *)xalloc((size_t)size + 1);
    size_t got = fread(buf, 1, (size_t)size, f);
    fclose(f);
    buf[got] = '\0';
    return buf;
}

static const char *tok_kind_name(int k) {
    switch (k) {
        case TK_EOF: return "EOF";
        case TK_INT: return "INT";
        case TK_FLOAT: return "FLOAT";
        case TK_STR: return "STRING";
        case TK_BYTES: return "BYTES";
        case TK_IDENT: return "IDENT";
        case TK_KEYWORD: return "KEYWORD";
        case TK_OP: return "OP";
        case TK_PUNCT: return "PUNCT";
        case TK_NL: return "NEWLINE";
        default: return "?";
    }
}

static void dump_tokens(void) {
    for (int i = 0; i < g_ntoks; i++) {
        Tok *t = &g_toks[i];
        if (t->kind == TK_NL) continue;
        printf("%d:%d\t%s\t%.*s\n", t->line, t->col, tok_kind_name(t->kind), t->len, t->s);
    }
}

/* 返回 0 成功；非 0 表示解析/运行错误（错误信息已打印）。 */

/* ------------------------------------------------------------------ */
/* 静态语义检查（明显非法代码在 C 驱动里也必须在执行前拒绝）            */
/* ------------------------------------------------------------------ */
typedef struct { const char *name; const char *type; } TypeBind;
typedef struct { TypeBind *items; int len; } TypeEnv;

static void te_set(TypeEnv *env, const char *name, const char *type) {
    for (int i = env->len - 1; i >= 0; i--) {
        if (strcmp(env->items[i].name, name) == 0) { env->items[i].type = type; return; }
    }
    env->items = (TypeBind *)realloc(env->items, sizeof(TypeBind) * (size_t)(env->len + 1));
    env->items[env->len].name = name;
    env->items[env->len].type = type;
    env->len++;
}
static const char *te_get(TypeEnv *env, const char *name) {
    for (int i = env->len - 1; i >= 0; i--)
        if (strcmp(env->items[i].name, name) == 0) return env->items[i].type;
    return NULL;
}
static int sem_is_int(const char *t) {
    if (!t) return 0;
    return strcmp(t,"i8")==0||strcmp(t,"i16")==0||strcmp(t,"i32")==0||
           strcmp(t,"i64")==0||strcmp(t,"u8")==0||strcmp(t,"u16")==0||
           strcmp(t,"u32")==0||strcmp(t,"u64")==0||strcmp(t,"isize")==0||
           strcmp(t,"usize")==0||strcmp(t,"int")==0||strcmp(t,"intlit")==0;
}
static int sem_is_unit(const char *t) {
    return !t || strcmp(t,"unit")==0 || strcmp(t,"void")==0;
}
static int sem_compat(const char *actual, const char *expected) {
    if (!actual || !expected) return 1;
    if (sem_is_unit(expected)) return sem_is_unit(actual) || strcmp(actual,"?")==0;
    if (sem_is_int(expected)) {
        if (!sem_is_int(actual)) return 0;
        if (strcmp(actual,"intlit")==0) return 1;
        return strcmp(actual, expected) == 0;
    }
    if (strcmp(expected,"f32")==0||strcmp(expected,"f64")==0) return strcmp(actual,"float")==0;
    if (strcmp(expected,"bool")==0) return strcmp(actual,"bool")==0;
    if (strcmp(expected,"str")==0) return strcmp(actual,"str")==0;
    if (expected[0]=='[') return strcmp(actual,"array")==0;
    return 1; /* 未知/复合类型：保守放行 */
}
static void sem_fail(Node *n, const char *msg) { ds_fail(n->line, n->col, "%s", msg); }

static const char *sem_find_ret(Node *prog, const char *name) {
    if (!prog || prog->kind != ND_PROGRAM) return NULL;
    for (int i = 0; i < prog->nitems; i++) {
        Node *it = prog->items[i];
        if (it->kind == ND_FN && strcmp(it->name, name) == 0) return it->type_name;
    }
    return NULL;
}
static const char *sem_infer(Node *e, TypeEnv *env, Node *prog);
static const char *sem_block_tail(Node *block, TypeEnv *env, Node *prog) {
    if (!block || block->kind != ND_BLOCK) return NULL;
    const char *last = NULL;
    for (int i = 0; i < block->nitems; i++) {
        Node *st = block->items[i];
        if (st->kind == ND_EXPRSTMT) last = sem_infer(st->a, env, prog);
        else if (st->kind == ND_IFEXPR) last = sem_infer(st, env, prog);
        else last = NULL;
        if ((st->kind == ND_EXPRSTMT || st->kind == ND_IFEXPR) && !last) last = "?";
    }
    return last;
}
static const char *sem_infer(Node *e, TypeEnv *env, Node *prog) {
    if (!e) return "unit";
    switch (e->kind) {
        case ND_LIT_INT: return "intlit";
        case ND_LIT_FLOAT: return "float";
        case ND_LIT_STR: return "str";
        case ND_LIT_BYTES: return "bytes";
        case ND_LIT_BOOL: return "bool";
        case ND_ARRAY: {
            const char *base = NULL;
            for (int i = 0; i < e->nitems; i++) {
                const char *t = sem_infer(e->items[i], env, prog);
                if (!t || strcmp(t, "?") == 0) continue;
                if (strcmp(t, "intlit") == 0) t = "i32";
                if (!base) base = t;
                else if (strcmp(base, t) != 0)
                    sem_fail(e, "数组元素类型不一致（无隐式提升）");
            }
            return "array";
        }
        case ND_MAP: return "map";
        case ND_VAR: return te_get(env, e->name);
        case ND_UNARY: return e->name && strcmp(e->name,"!")==0 ? "bool" : sem_infer(e->a, env, prog);
        case ND_BINARY: {
            const char *op = e->name ? e->name : "";
            if (strcmp(op,"==")==0||strcmp(op,"!=")==0||strcmp(op,"<")==0||
                strcmp(op,">")==0||strcmp(op,"<=")==0||strcmp(op,">=")==0||
                strcmp(op,"&&")==0||strcmp(op,"||")==0) return "bool";
            const char *a = sem_infer(e->a, env, prog), *b = sem_infer(e->b, env, prog);
            if (strcmp(op,"+")==0 && ((a&&strcmp(a,"str")==0)||(b&&strcmp(b,"str")==0))) return "str";
            if ((a&&strcmp(a,"float")==0)||(b&&strcmp(b,"float")==0)) return "float";
            if (sem_is_int(a) && sem_is_int(b)) {
                if (strcmp(a,"intlit")==0 && strcmp(b,"intlit")==0) return "intlit";
                if (strcmp(a,"intlit")==0) return b;
                if (strcmp(b,"intlit")==0) return a;
                if (strcmp(a,b)==0) return a;
                return NULL;
            }
            return NULL;
        }
        case ND_CALL: {
            for (int i = 0; i < e->nitems; i++) sem_infer(e->items[i], env, prog);
            if (!e->a || e->a->kind != ND_VAR) return NULL;
            const char *n = e->a->name;
            if (strcmp(n,"p")==0||strcmp(n,"println")==0||strcmp(n,"print")==0) return "unit";
            if (strcmp(n,"str")==0) return "str";
            if (strcmp(n,"len")==0) return "int";
            if (strcmp(n,"range")==0) return "array";
            return sem_find_ret(prog, n);
        }
        case ND_IFEXPR: {
            const char *a = (e->b && e->b->kind==ND_BLOCK) ? sem_block_tail(e->b, env, prog) : NULL;
            const char *b = (e->c && e->c->kind==ND_BLOCK) ? sem_block_tail(e->c, env, prog) :
                            (e->c ? sem_infer(e->c, env, prog) : NULL);
            if (a && b) {
                if (strcmp(a,"intlit")==0 && sem_is_int(b)) a = b;
                else if (strcmp(b,"intlit")==0 && sem_is_int(a)) b = a;
                if (strcmp(a,b)!=0) sem_fail(e, "if 分支类型不一致");
                return a;
            }
            return NULL;
        }
        case ND_BLOCKEXPR: return sem_block_tail(e->b, env, prog);
        default: return NULL;
    }
}
static void sem_check_stmt(Node *st, TypeEnv *env, Node *prog, const char *ret,
                           int in_fn, int loop_depth, int *has_return);
static void sem_check_block(Node *block, TypeEnv *env, Node *prog, const char *ret,
                            int in_fn, int loop_depth, int *has_return) {
    if (!block || block->kind != ND_BLOCK) return;
    for (int i = 0; i < block->nitems; i++)
        sem_check_stmt(block->items[i], env, prog, ret, in_fn, loop_depth, has_return);
}
static void sem_check_cond(Node *cond, TypeEnv *env, Node *prog, Node *at) {
    const char *t = sem_infer(cond, env, prog);
    if (t && strcmp(t,"bool")!=0 && strcmp(t,"?")!=0)
        sem_fail(at, "条件必须是 bool");
}
static void sem_check_stmt(Node *st, TypeEnv *env, Node *prog, const char *ret,
                           int in_fn, int loop_depth, int *has_return) {
    if (!st) return;
    switch (st->kind) {
        case ND_LET: {
            const char *actual = sem_infer(st->a, env, prog);
            if (st->type_name && !sem_compat(actual, st->type_name))
                ds_fail(st->line, st->col, "`%s` 类型不匹配：标注 %s，实际 %s",
                        st->name, st->type_name, actual ? actual : "?");
            te_set(env, st->name, st->type_name ? st->type_name :
                   (actual && strcmp(actual,"intlit")==0 ? "i32" : actual));
            return;
        }
        case ND_ASSIGN: {
            const char *actual = sem_infer(st->b, env, prog);
            if (st->a && st->a->kind == ND_VAR) {
                const char *tt = te_get(env, st->a->name);
                if (tt && actual && !sem_compat(actual, tt))
                    ds_fail(st->line, st->col, "赋值类型不匹配：目标 %s，值 %s", tt, actual);
            }
            return;
        }
        case ND_RETURN:
            if (!in_fn) sem_fail(st, "`return` 只能出现在函数内");
            if (has_return) *has_return = 1;
            if (st->a) {
                const char *actual = sem_infer(st->a, env, prog);
                if (!sem_is_unit(ret) && !sem_compat(actual, ret))
                    ds_fail(st->line, st->col, "`return` 类型不匹配：期望 %s，实际 %s",
                            ret, actual ? actual : "?");
            } else if (!sem_is_unit(ret)) {
                sem_fail(st, "函数声明返回类型，`return` 需要值");
            }
            return;
        case ND_IFEXPR:
            sem_check_cond(st->a, env, prog, st);
            if (st->b) sem_check_block(st->b, env, prog, ret, in_fn, loop_depth, has_return);
            if (st->c) sem_check_stmt(st->c, env, prog, ret, in_fn, loop_depth, has_return);
            return;
        case ND_BLOCK:
            sem_check_block(st, env, prog, ret, in_fn, loop_depth, has_return);
            return;
        case ND_WHILE:
            sem_check_cond(st->a, env, prog, st);
            sem_check_block(st->b, env, prog, ret, in_fn, loop_depth + 1, has_return);
            return;
        case ND_LOOP:
            sem_check_block(st->b, env, prog, ret, in_fn, loop_depth + 1, has_return);
            return;
        case ND_FOR:
            sem_infer(st->a, env, prog);
            sem_check_block(st->b, env, prog, ret, in_fn, loop_depth + 1, has_return);
            return;
        case ND_BREAK:
        case ND_CONTINUE:
            if (loop_depth <= 0) sem_fail(st, "`break`/`continue` 只能出现在循环内");
            return;
        case ND_EXPRSTMT:
            sem_infer(st->a, env, prog);
            return;
        default:
            sem_infer(st, env, prog);
    }
}
static void sem_check_fn(Node *fn, Node *prog) {
    const char *ret = fn->type_name;
    if (ret && strcmp(ret,"void")==0) ret = "unit";
    TypeEnv env = {0};
    for (int i = 0; i < fn->nparams; i++)
        te_set(&env, fn->params[i].name, fn->params[i].type);
    int has_return = 0;
    if (fn->a && fn->a->kind == ND_BLOCK) {
        sem_check_block(fn->a, &env, prog, ret, 1, 0, &has_return);
        const char *tail = sem_block_tail(fn->a, &env, prog);
        if (tail && strcmp(tail,"?")!=0 && !sem_is_unit(ret) && !sem_compat(tail, ret))
            ds_fail(fn->line, fn->col, "函数 `%s` 返回类型不匹配：期望 %s，尾表达式为 %s",
                    fn->name, ret, tail);
        if (!sem_is_unit(ret) && !has_return && !tail)
            ds_fail(fn->line, fn->col, "函数 `%s` 声明返回 %s，但没有 return 或尾表达式",
                    fn->name, ret);
    } else if (fn->a) {
        const char *actual = sem_infer(fn->a, &env, prog);
        if (!sem_is_unit(ret) && !sem_compat(actual, ret))
            ds_fail(fn->line, fn->col, "函数 `%s` 返回类型不匹配：期望 %s，实际 %s",
                    fn->name, ret, actual ? actual : "?");
    } else if (!sem_is_unit(ret)) {
        ds_fail(fn->line, fn->col, "函数 `%s` 没有函数体", fn->name);
    }
    free(env.items);
}
static void check_semantics(Node *prog) {
    if (!prog || prog->kind != ND_PROGRAM) return;
    TypeEnv top = {0};
    for (int i = 0; i < prog->nitems; i++) {
        Node *it = prog->items[i];
        if (it->kind == ND_FN) sem_check_fn(it, prog);
        else if (it->kind == ND_LET) {
            const char *actual = sem_infer(it->a, &top, prog);
            if (it->type_name && !sem_compat(actual, it->type_name))
                ds_fail(it->line, it->col, "`%s` 类型不匹配：标注 %s，实际 %s",
                        it->name, it->type_name, actual ? actual : "?");
            te_set(&top, it->name, it->type_name ? it->type_name :
                   (actual && strcmp(actual,"intlit")==0 ? "i32" : actual));
        } else {
            sem_check_stmt(it, &top, prog, NULL, 0, 0, NULL);
        }
    }
    free(top.items);
}

static int run_text(const char *src, const char *file, int repl_mode, int dump, int check_mode) {
    if (setjmp(g_err)) {
        fprintf(stderr, "error: %s\n", g_errmsg);
        return 1;
    }
    g_file = file;
    setup_flow(file, src);
    g_ntoks = 0;
    lex_source(src);
    if (dump) {
        dump_tokens();
        return 0;
    }
    P_POS = 0;
    Node *prog = parse_program(repl_mode);
    check_semantics(prog);
    if (check_mode) return 0;
    Value *last = v_unit();
    run_program(prog, repl_mode, &last);
    if (!repl_mode) {
        if (!g_had_top_stmts) run_main_if_present();
    } else if (last->kind != VL_UNIT) {
        printf("=> %s\n", v_repr(last));
    }
    return 0;
}

/* 括号/字符串未闭合 → REPL 续行 */
static int needs_continuation(const char *src) {
    int depth = 0;
    int in_str = 0, escape = 0;
    for (const char *p = src; *p; p++) {
        char c = *p;
        if (in_str) {
            if (escape) escape = 0;
            else if (c == '\\') escape = 1;
            else if (c == '"') in_str = 0;
            continue;
        }
        if (c == '"') { in_str = 1; continue; }
        if (c == '#') {
            while (*p && *p != '\n') p++;
            if (!*p) break;
            continue;
        }
        if (c == '(' || c == '[' || c == '{') depth++;
        else if (c == ')' || c == ']' || c == '}') depth--;
    }
    return depth > 0 || in_str;
}

static void repl_command(const char *line, int *quit);

static void repl(int quiet) {
    if (!quiet) {
        printf("Ds v%s C 驱动 REPL（:help 查看命令，Ctrl-D 退出）\n", DS_VERSION);
    }
    int interactive = isatty(0);
    char *buffer = NULL;
    size_t blen = 0, bcap = 0;
    buffer = (char *)malloc(1);
    buffer[0] = '\0';

    for (;;) {
        if (interactive) {
            fputs(blen ? "... " : "ds> ", stdout);
            fflush(stdout);
        }
        char *line = NULL;
        size_t cap = 0;
        ssize_t n = getline(&line, &cap, stdin);
        if (n < 0) {
            free(line);
            if (interactive) putchar('\n');
            break;
        }
        while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = '\0';

        if (blen == 0) {
            int quit = 0;
            if (line[0] == ':') {
                repl_command(line, &quit);
                if (quit) { free(line); break; }
                continue;
            }
            if (n == 0) { free(line); continue; }
        }
        blen += (size_t)n + 1;
        if (blen > bcap) {
            bcap = bcap ? bcap * 2 : 256;
            buffer = (char *)realloc(buffer, bcap);
        }
        if (buffer[0] != '\0' && blen > (size_t)n + 1) strcat(buffer, "\n");
        strcat(buffer, line);
        free(line);

        if (needs_continuation(buffer)) continue;

        run_text(buffer, "<repl>", 1, 0, 0);
        buffer[0] = '\0';
        blen = 0;
    }
    free(buffer);
}

static void repl_command(const char *line, int *quit) {
    if (strcmp(line, ":quit") == 0 || strcmp(line, ":q") == 0 || strcmp(line, ":exit") == 0) {
        *quit = 1;
        return;
    }
    if (strcmp(line, ":help") == 0) {
        printf("命令:\n");
        printf("  :help            显示本帮助\n");
        printf("  :quit / :q       退出\n");
        printf("  :reset           重置解释器状态\n");
        printf("  :load <文件>      运行一个 .ds 文件\n");
        printf("  :version         版本\n");
        printf("直接输入 Ds 代码回车执行；未闭合的块/括号会自动续行。\n");
        return;
    }
    if (strcmp(line, ":version") == 0) {
        printf("Ds v%s（C 驱动）\n", DS_VERSION);
        return;
    }
    if (strcmp(line, ":reset") == 0) {
        g_global = env_new(NULL);
        register_builtins();
        printf("(已重置)\n");
        return;
    }
    if (strncmp(line, ":load ", 6) == 0) {
        const char *path = line + 6;
        while (*path == ' ') path++;
        if (setjmp(g_err)) {
            fprintf(stderr, "error: %s\n", g_errmsg);
            return;
        }
        char *src = read_file_text(path);
        g_file = path;
        g_ntoks = 0;
        lex_source(src);
        P_POS = 0;
        Node *prog = parse_program(0);
        Value *last = v_unit();
        run_program(prog, 0, &last);
        run_main_if_present();
        return;
    }
    printf("未知命令：%s（:help）\n", line);
}

static void usage(FILE *out, const char *prog) {
    fprintf(out,
            "用法: %s [选项] [文件.ds]\n"
            "      %s -c '代码'\n"
            "\n"
            "Ds v%s 原生 C 驱动（核心子集；词法/解析/解释执行全部为 C 实现）。\n"
            "\n"
            "选项:\n"
            "  -c, --code <代码>     直接执行一段 Ds 源码\n"
            "  --check               仅做词法/解析检查\n"
            "  --emit tokens         打印词法记号表\n"
            "  --repl                进入交互式终端\n"
            "  --app / --bare        应用 / 裸机模式（互斥；C 版仅做参数校验）\n"
            "  --target <triple>     目标三元组（记录，不产机器码）\n"
            "  --opt <级别>          优化级别（记录）\n"
            "  --gc <策略>           none/rc/arc/tracing（`--bare` 只允许 none）\n"
            "  --rt <运行时>         none/minimal/full\n"
            "  -o <输出>             [兼容参数] 不产可执行文件\n"
            "  -q, --quiet           安静模式\n"
            "  --version             版本\n"
            "  -h, --help            帮助\n"
            "\n"
            "示例:\n"
            "  %s examples/hello.ds\n"
            "  %s -c 'package t\\nfn main() { println(\"hi\") }'\n",
            prog, prog, DS_VERSION, prog, prog);
}

int main(int argc, char **argv) {
    const char *prog = base_name(argv[0] ? argv[0] : "ds");
    int is_dscc = strcmp(prog, "dscc") == 0;
    const char *file = NULL;
    const char *code = NULL;
    int check = 0, dump = 0, repl_flag = 0, quiet = 0;
    int app = 0, bare = 0, gc_none = 1, rt_full = 0;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            usage(stdout, prog);
            return 0;
        }
        if (strcmp(a, "--version") == 0) {
            printf("%s (Ds v%s, C driver)\n", prog, DS_VERSION);
            return 0;
        }
        if (strcmp(a, "-q") == 0 || strcmp(a, "--quiet") == 0) { quiet = 1; continue; }
        if (strcmp(a, "-v") == 0 || strcmp(a, "--verbose") == 0) continue;
        if (strcmp(a, "-c") == 0 || strcmp(a, "--code") == 0) {
            if (++i >= argc) { fprintf(stderr, "%s: error: -c 需要代码\n", prog); return 2; }
            code = argv[i];
            continue;
        }
        if (strcmp(a, "--check") == 0) { check = 1; continue; }
        if (strcmp(a, "--repl") == 0) { repl_flag = 1; continue; }
        if (strcmp(a, "--app") == 0) { app = 1; continue; }
        if (strcmp(a, "--bare") == 0) { bare = 1; continue; }
        if (strcmp(a, "--emit") == 0) {
            if (++i >= argc) { fprintf(stderr, "%s: error: --emit 需要参数\n", prog); return 2; }
            if (strcmp(argv[i], "tokens") == 0) { dump = 1; continue; }
            if (strcmp(argv[i], "run") == 0 || strcmp(argv[i], "check") == 0) continue;
            fprintf(stderr, "%s: error: C 驱动暂不支持 --emit %s\n", prog, argv[i]);
            return 2;
        }
        if (strcmp(a, "--target") == 0 || strcmp(a, "--opt") == 0 ||
            strcmp(a, "--gc") == 0 || strcmp(a, "--rt") == 0 || strcmp(a, "-o") == 0 ||
            strcmp(a, "--output") == 0) {
            if (++i >= argc) { fprintf(stderr, "%s: error: %s 需要参数\n", prog, a); return 2; }
            if (strcmp(a, "--gc") == 0) gc_none = (strcmp(argv[i], "none") == 0);
            if (strcmp(a, "--rt") == 0) rt_full = (strcmp(argv[i], "full") == 0);
            continue;
        }
        if (a[0] == '-') {
            fprintf(stderr, "%s: error: 未知选项 %s\n", prog, a);
            return 2;
        }
        file = a;
    }

    if (app && bare) { fprintf(stderr, "%s: error: --app 与 --bare 互斥\n", prog); return 2; }
    if (bare && !gc_none) { fprintf(stderr, "%s: error: --bare 下只允许 --gc none\n", prog); return 2; }
    if (bare && rt_full) { fprintf(stderr, "%s: error: --bare 下不允许 --rt full\n", prog); return 2; }

    g_global = env_new(NULL);
    register_builtins();

    if (repl_flag || (!file && !code)) {
        if (is_dscc && !repl_flag) {
            usage(stderr, prog);
            return 2;
        }
        repl(quiet);
        return 0;
    }

    if (code) {
        return run_text(code, "<code>", 0, dump, check);
    }
    char *src = NULL;
    if (setjmp(g_err)) {
        fprintf(stderr, "error: %s\n", g_errmsg);
        return 1;
    }
    src = read_file_text(file);
    return run_text(src, file, 0, dump, check);
}
