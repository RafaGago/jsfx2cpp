Notice
======

I'm leaving Github. The main official location for this project is now:
https://codeberg.org/RafaGago/jsfx2cpp

jsfx2cpp
========

An aid in manually converting Reaper's JSFX (interpreted code)to C++.

TL; DR
> ./jsfx2cpp.py -f jsfx-samples/real-jsfx | clang-format --style LLVM

It generates a class of almost valid C++ code that is intended to be used as a
starting point when manually porting JSFX DSP code (Cockos's Reaper JIT DSP
language derived from EEL2) to C++.

The generated code has stubs that have to be implemented afterwards, related
e.g. to memory allocation, time/BPM requesting, FFT function calls, etc. It
completely ignores the graphics/interface.

The JSFX language is not fully speced, so many features were discovered very
late unfortunately, e.g. namespace parameters. Those would require a rewrite
which won't happen because in practice very few programs use it.

An example of class generated with this program:
https://github.com/RafaGago/artv-audio/blob/master/src/artv-common/dsp/chokehold/gate_expander.hpp

The codebase has Proof of concept code quality. It could use some refactors here
and there:

* No unit testing.
* Total disregard for speed/efficiency. Favoring simplicity.
* Not a lot of documentation etc..
* Coding on a big single file.
* The error output is rudimentary

Deliberate known issues/omissions:

* "this.." not implemented, just "this.". I have not seen a single script used.
* strings. Those are mostly used on the GUI part, this project only is concerned
  with the DSP.

Non-deliberate known issues/omissions:

* Only single function namespaces. E.g. fn(namespace*). The current
  implementation is based on substituting by "this" and namespace calls when
  possible. This JSFX features was found very late on the development cycle
  after successfully parsing  many non-trivial JSFX scripts. It is a non
  documented a seldomly used feature.

* Another feature I found very late. On JSFX calling a function with less
  parameters than the function expects succeeds by defaulting missing parameters
  to 0. I didn't even bother checking parameter counts as I was assuming that
  correct JSFX code would never do that. Just add explicit 0's for missing
  parameterson the generated code.

* Comments are a bit flaky. If some file doesn't work because of the comments
  just temporarily remove them. PLY uses regexes for lexing, which doesn't play
  well. This could just be fixed by doing it on the preprocessing stage. At some
  point it could be interesting for the source's comments to make it to the
  generated code.

If I were to write this again I would probably use a statically typed language.
It is good as a POC but I consider risky for my taste to keep growing this
project in Python.

Note for me on the future, this is a good project to rewrite in Go or Nim.
