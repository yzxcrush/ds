CC ?= cc
CFLAGS ?= -O2 -std=gnu11 -Wall -Wextra -Wno-unused-parameter
LDLIBS = -lm

all: build/ds

build/ds: ds.c
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ ds.c $(LDLIBS)

install: build/ds
	@mkdir -p $(DESTDIR)$(PREFIX)/bin
	install -m 755 build/ds $(DESTDIR)$(PREFIX)/bin/ds
	install -m 755 build/ds $(DESTDIR)$(PREFIX)/bin/dscc

clean:
	rm -rf build

.PHONY: all install clean
