import os
import re

def jsfx_preprocess(
    jsfx, selected_sections, include_paths=[], start_section = 'desc', depth = 0
    ):
    sections = {}
    for section in selected_sections:
        sections[section] = []

    section = start_section
    sliders = []
    provides = None
    includes = list (include_paths)

    for line in jsfx:
        stripline = line.strip()

        # order dependant on the conditional that sets "provides = []"
        if provides is not None:
            if line.startswith ('@') or re.match (r'[a-z]+:', stripline):
                # provides list ended
                extradirs = []
                for provide in provides:
                    # TODO: do proper globbing
                    d = os.path.dirname (provide)
                    if d != '':
                        extradirs.append (d)
                for include in list (includes):
                    for extradir in extradirs:
                        includes.append (os.path.join (include, extradir))
                provides = None
            else:
                provides.append (stripline)

        if section == 'desc' and line.lstrip().startswith ('provides:'):
            provides = [] # enable parsing of provides field

        if line.lstrip().startswith ('import ') and \
            (section in selected_sections or section == 'desc'):

            filename = line[len ('import '):].strip()
            found = False
            for path in includes:
                fpath = os.path.join (path, filename)
                try:
                    with open (fpath, 'r') as file:
                        content = file.readlines()
                    sub_sections = jsfx_preprocess(
                        content,
                        selected_sections,
                        include_paths,
                        section,
                        depth + 1
                        )
                    found = True
                    break
                except FileNotFoundError:
                    pass
            if not found:
                raise RuntimeError(
                    f'import not found: "{filename}" in paths: {include_paths}'
                    )

            for k, v in sub_sections.items():
                sections[k] += v
            continue

        if line.lstrip().startswith ('@'):
            section = line[len ('@'):].strip()
            continue

        if section == 'desc' and line.strip().startswith ('slider'):
            sliders.append (f'{line.strip()}')

        if section in selected_sections:
            sections[section].append (line.rstrip())

    if depth > 0:
        # only interesting for recursion
        return sections

    # depth = 0
    program = []
    for section in selected_sections:
        code = sections[section]
        if (len (code) == 0):
            continue
        program.append (f'@{section}')
        program += code

    return '\n'.join (program), sliders
