#!/usr/bin/env python3
import argparse
import inspect
import fileinput
from lexer import lexer, CompileError
from parser import parser
from generator import generate
from preprocessor import jsfx_preprocess
from os import path as ospath

def run_lexer(program):
    lexer.input(program)
    while True:
        tok = lexer.token()
        if not tok:
            break      # No more input
        print(tok)

def get_ast(program):
    return

def main():
    p= argparse.ArgumentParser(description="Quick and dirty jsfx2cpp")

    p.add_argument ("-f", "--file", help="file to parse, otherwise stdin")
    p.add_argument(
        "-m",
        "--mode",
        choices=['parser', 'lexer', 'ast', 'cpp', 'preprocessor'],
        default='cpp',
        help='output mode'
        )
    p.add_argument(
        "-d",
        "--debug",
        default=False,
        action='store_true',
        help='passing debug to PLY'
        )
    p.add_argument(
        "-l",
        "--library-functions",
        action='append',
        default=[],
        help="json file containing mappings of jsfx to c++ calls, 'see jsfx_default_library_functions.json'. This parameter can be repeated. The dictionaries will be merged in that case, giving more preference to the last occurences in case of key collisions."
        )
    p.add_argument(
        "--no-sample-into-block-merge",
        default=False,
        action='store_true',
        help='the generator merges the "sample" section into the "block" section. This might cause a duplicated definition for shadowed functions on these blocks. Enable if the generator throws an exception saying so.'
        )

    args = p.parse_args()
    if args.file is not None:
        with open (args.file, 'r') as file:
            main_jsfx = file.readlines();
        include_paths = [ospath.dirname (args.file)]
    else:
        main_jsfx = []
        # '-' is required, so stdin parses no arguments
        for line in fileinput.input(files='-'):
            main_jsfx.append (line.rstrip())
        include_paths = ['.']

    # Order matters, as "slider" runs after "init". As JSFX is a dynamic
    # language the order on which variables appear is important.
    selected_sections = ['init', 'slider', 'block', 'sample']
    program, slider_jsfx = \
        jsfx_preprocess (main_jsfx, selected_sections, include_paths)
    if args.mode == 'preprocessor':
        print (program)
        return 0

    if args.mode == 'lexer':
        run_lexer (program)
        return 0

    try:
        ast = parser.parse (program, lexer=lexer, debug=args.debug)
    except CompileError as ce:
        lstart = program.rfind ('\n', 0, ce.idx)
        lstart = lstart if lstart >= 0 else 0
        lend = program.find ('\n', ce.idx)
        lend = lend if lend >= 0 else len (program)
        pos = ce.idx - lstart
        f = args.file if args.file else 'stdin'
        lnum = program[:lend].count ('\n') + 1
        print (f'preprocessed: {f}:{lnum}:{pos}: {ce}')
        print (' ' + program[lstart:lend])
        print (f'{" " * (pos - 1)}^')
        return 1

    if args.mode == 'parser':
        print (ast)
        return 0

    lib_funcs = args.library_functions
    if len (lib_funcs) == 0:
        lib_funcs.append ('jsfx_default_library_functions.json')

    code, transformed_ast = generate(
        ast,
        lib_funcs,
        "jsfx_special_variables.json",
        slider_jsfx,
        not args.no_sample_into_block_merge
        )
    if args.mode == 'ast':
        print (transformed_ast)
    else:
        print (code)
    return 0

if __name__ == "__main__":
    main()
