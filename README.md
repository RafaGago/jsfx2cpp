An aid in manually converting Reaper's JSFX (interpreted code)to C++.

| ./jsfx2cpp.py -f jsfx-samples/real-jsfx | clang-format --style LLVM

It generates a class of almost valid C++ code as a starting point of a JSFX to
C++ porting effort.

This is a personal tool, coded for fun. I'm not trained as a computer scientist
and it's the first time of me coding some (naîve, kindof) compiler. Expect this
to show. It is almost sure for some things to be possible to be done in a better
way.

My plans were to convert some JSFX to C++ with it afterwards, but I lost steam
after buying lots of audio plugins on Black Friday and Christmas. So I share
this code in case someone finds it useful.

In the current status, if I remember correctly, I was that is is able to parse
complex JSFX programs (e.g. Saike's) and the sources looked good, but I never
tested integrating the generated code to JUCE.

I was about to implement an optimization pass to try to convert chained if/else
statements to switches and then try to port some FX.

The codebase has Proof of concept code quality. It could use some refactors here
and there:

* No unit testing.
* Total disregard for speed/efficiency. Favoring code clarity.
* Not a lot of documentation etc..
* Coding on a big file.
* The error output could be improved

Deliberate known issues/omissions:

* "this.." not implemented, just "this.".
* strings.

Non-deliberate known issues/omissions:

The list below are just surprises that just popped up  due to lack of formal
specification/documentation on the language. These JSFX features were found very
late after successfuilly parsing many non-trivial JSFX scripts:

* Only single function namespaces. E.g. fn(namespace*). The current
  implementation is based on substituting by "this" and namespace calls when
  possible.

While fixeable, these features are sparsely used and the generator fails loudly,
so I'm temporarilly editing the scripts that don't translate manually before
deciding if doing things right is worth the effort. Both appeared on some
Geraint Luff's scripts.
