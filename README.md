A port of https://github.com/peterjc/backports.lzma to cffi, which adds seeking support. You must compress your xz files with the `--block-size` option for `lzmaffi` to efficiently seek through them.

Example:

```py
import lzmaffi
import io

f = lzmaffi.open('log.xz', mode='rb')

# f has all the usual file object methods like io.open

for offset in f.block_boundaries:
	f.seek(offset)
	snippet = f.read(80)
	print "{0}: {1}...".format(offset, snippet)

# You can also seek to arbitrary locations
f.seek(-80, io.SEEK_END)
offset = f.tell()
snippet = f.read(80)
print "{0}: {1}...".format(offset, snippet)

```

Example output:
```
Tomers-MacBook-Pro:~ tomer$ python ex.py 
0: Let us now consider repetition clauses (like, while B repeat A or repeat A until...
400: ning pattern known as "induction" makes us well equipped to retain our intellect...
800: nal number of the corresponding current repetition. As repetition clauses (just ...
1200: program or by the dynamic evolution of the process) whether he wishes or not. Th...
1600: he number, n say, of people in an initially empty room, we can achieve this by i...
2000: nce that it becomes terribly hard to find a meaningful set of coordinates in whi...
2400: niquely by a counter counting the number of actions performed since program star...
2800:  stands is just too primitive; it is too much an invitation to make a mess of on...
3200: dinate system can be maintained to describe the process in a helpful and managea...
3600: early 1959 in Copenhagen quite explicitly expressed his doubts whether the go to...
4000: e use of the go to statement to alarm exits, but I have not been able to trace i...
4400: troducing a large number of labels in the program."
...
4372: t eliminates the need for introducing a large number of labels in the program."
...
```

[![Build Status](https://secure.travis-ci.org/r3m0t/backports.lzma.png?branch=cffi)](https://travis-ci.org/r3m0t/backports.lzma)
