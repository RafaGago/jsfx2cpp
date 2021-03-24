from enum import Enum
from parser import Node
from sys import stderr
from copy import deepcopy
import re
import json
import jsonschema

GLOBAL_Section = 'init'
STATIC_MEM_ARRAY = 'mempool'
LOOP_TEMP = '$$loop_ret_'
#-------------------------------------------------------------------------------
def warn(txt):
    print(txt, file=stderr)
#-------------------------------------------------------------------------------
def _create_identifier_node (name, line=0):
    return Node ('identifier', [name], bottom=True, line=line)

# TODO change all code to use this.
def _get_identifier_key (node):
    assert (node.type == 'identifier')
    return _make_key (node.lhs)
#-------------------------------------------------------------------------------
class VisitorGlobalState:
    def __init__(self, section='invalid'):
        self.section = section

class VisitorInfo:
    def __init__(
        self,
        node,
        parent = None,
        on_lhs = True,
        idx = 0,
        last = 0,
        parent_info = None,
        state = None
        ):
        assert (type (node) == Node)

        if parent_info is not None:
            parent = parent_info.node
            self.stack = [node] + parent_info.stack
            self.state = parent_info.state
        else:
            if parent is None:
                parent = Node ('virtual-parent', [node])
            self.stack = [node, parent]
            self.state = VisitorGlobalState() if state is None else state

        self.node      = node # alias for self[0] or self.stack[0]
        self.parent    = parent # alias for self[0] or self.stack[1]
        self.on_lhs    = on_lhs
        self.idx       = idx
        self.last_idx  = last

    def get_node_type_stack(self, minsize=0):
        ret = [n.type for n in self.stack]
        size = len (ret)
        if size < minsize:
            ret += [''] * (minsize - size)
        return ret

    def node_type_seq_match (self, offset, sequences):
        minsize = len (max (sequences, key=len))
        minsize += offset
        typestack = self.get_node_type_stack (minsize)
        for seq in sequences:
            if typestack[offset : offset + len (seq)] == seq:
                return True
        return False

    def __getitem__(self, idx):
        return self.stack[idx]

    def __setitem__(self, idx, value):
        self.stack[idx] = value

    def __len__(self):
        return len (self.stack)

    def __str__(self):
        s = self
        return f"type: '{s.node.type}', ptype: '{s.parent.type}', lhs: {s.on_lhs}, idx: {s.idx}, slast: {s.last_idx}, depth: {s.seq_depth}"

    def copy(self):
        return deepcopy(self)

class VisitType(Enum):
    # Notice, visits of LHS and RHS are recursive all the way to the bottom, so
    # e.g. visiting the node after the LHS means that all the LHS has been
    # traveled.
    NODE_FIRST          = 1, # visits parent, LHS, then RHS
    NODE_AFTER_LHS      = 2, # visits LHS, parent, then RHS
    NODE_AFTER_RHS      = 3, # visits LHS, RHS, then parent
    NODE_ALL            = 4, # visits parent, LHS, parent, RHS, parent
    NODE_BOTH_SIDES     = 5, # visits parent, LHS, RHS, parent
    NODE_ONLY           = 6, # visits only the parent, breaks the recursion
    NODE_ALL_EXCEPT_RHS = 7, # visits LHS and parent

# visits the tree
#
#-"info" is the top (current ) node.
#
#-"visiting_new": A function that will always be visited when traveling down the
#   graph on a new node. It decides how the visit will be done on this node by
#   returning any of the values on "VisitType". It can also apply
#   transformations before the visit starts.
#
#-"visit": The function that visits nodes.
#
#-"visit_state":  An object that will always be passed provided to both the
#   "visiting_new" and "visit" functions. Useful e.g. to store results

def _tree_visit_side(side, vnew, visitor, state, parentinfo, on_lhs):
    last_state = parentinfo.state
    for idx, n in enumerate (side):
        if type (n) != Node:
            print (parentinfo.parent)
            assert(False)
        last = len (side) - 1
        inf = VisitorInfo(
            node=n, on_lhs=on_lhs, idx=idx, last=last, parent_info=parentinfo
            )
        last_state = _tree_visit (inf, vnew, visitor, state)
    return last_state

def _tree_visit(
    info,
    visiting_new,
    visit,
    visit_state = None,
    ):
    assert (type (info) == VisitorInfo)
    assert (callable (visiting_new))
    assert (callable (visit))

    if info.node.type == 'section':
        info.state.section = info.node.lhs

    if info.node.is_bottom:
        # breaking the visit down
        visit (info, visit_state)
        return info.state

    visit_t = visiting_new (info, visit_state)

    if visit_t is VisitType.NODE_ONLY:
        # not going to visit down
        visit (info, visit_state)
        return info.state

    if visit_t is VisitType.NODE_FIRST or \
        visit_t is VisitType.NODE_ALL or \
        visit_t is VisitType.NODE_ALL_EXCEPT_RHS or \
        visit_t is VisitType.NODE_BOTH_SIDES:

        visit (info, visit_state)

    info.state = _tree_visit_side(
        info.node.lhs, visiting_new, visit, visit_state, info, on_lhs=True
        )
    if visit_t is VisitType.NODE_AFTER_LHS or \
        visit_t is VisitType.NODE_ALL or \
        visit_t is VisitType.NODE_ALL_EXCEPT_RHS:

        visit (info, visit_state)

    if visit_t is VisitType.NODE_ALL_EXCEPT_RHS:
        return info.state

    info.state = _tree_visit_side(
        info.node.rhs, visiting_new, visit, visit_state, info, on_lhs=False
        )
    if visit_t is VisitType.NODE_AFTER_RHS or \
        visit_t is VisitType.NODE_ALL or \
        visit_t is VisitType.NODE_BOTH_SIDES:

        visit (info, visit_state)

    return info.state
#-------------------------------------------------------------------------------
class QueryState:
    def __init__(self, _query):
        self._query = _query
        self.match = []

def _query(node, query_fn, node_parent=None):
    # runs a _query, It doesn't travel into compound statements (seq). Results
    # are bottom to top
    def visiting_new (info, _):
        assert (type (info) == VisitorInfo)

        if info.node.type == 'seq':
            return VisitType.NODE_ONLY # will call flatten_assignments on seq
        return VisitType.NODE_AFTER_LHS

    def visitor (info, state):
        assert (type (info) == VisitorInfo)
        assert (type (state) == QueryState)

        if state._query(info):
            state.match.append (info)

    state = QueryState (query_fn)
    info = VisitorInfo (node, node_parent)
    _tree_visit (info, visiting_new, visitor, state)
    return state.match
#-------------------------------------------------------------------------------
def _flatten_multiple_assignments_in_expression (head_node):
    # Flattens assignments.
    #
    # The idea is to flatten assignments like those below:
    # echo "x = (y = x) + z" | ./eel2c.py --mode ast
    # echo "x = (y = x)" | ./eel2c.py --mode ast
    #
    # This is just for making the next transformations and the generated code
    # easier to reason about. I personally dislike multiple assignments on the
    # same line too.
    #
    # This functions also converts any branch on a 'loop' or an 'if' having
    # assignments to a sequence (compound statement)(read code comment below).
    #
    # Note, this is an early implementation before having the VisitorInfo.branch
    # (the node stack).

    assert(head_node.type == 'seq')

    def flatten_assignments_on_seq_if(side, idx):
        node = side[idx]
        if node.type != 'seq':
            equals = _query (node, lambda info: info.node.type == '=')
            if len (equals) > 0:
                # some assignments, we do a conversion to a sequence
                node = Node ("seq", [node], line=node.line)

        side[idx] = node

    def visiting_new(info, _):
        assert (type (info) == VisitorInfo)
        # converting some of the children expressions on these constructs to
        # sequences when traveling down the tree. This is for an easier
        # implementation on the main loop. It has no harmful side effects.
        if info.node.type == 'if':
            flatten_assignments_on_seq_if (info.node.rhs, 0)
            if len (info.node.rhs) == 2:
                flatten_assignments_on_seq_if (info.node.rhs, 1)

        elif info.node.type == 'function':
            flatten_assignments_on_seq_if (info.node.rhs, 0)

        elif info.node.type.startswith ('loop'):
            flatten_assignments_on_seq_if (info.node.rhs, 0)

        if info.node.type == 'seq':
            # sequences stop the visit down its branch, they have to be
            # manually traveled sideways with a new call to the
            # "_flatten_multiple_assignments_in_expression" function
            return VisitType.NODE_ONLY

        return VisitType.NODE_AFTER_LHS

    def visitor(info, assign_lst):
        assert (type (info) == VisitorInfo)

        if info.node.type == '=':
            assign_lst.append (info)

        elif info.node.type == 'seq':
            _flatten_multiple_assignments_in_expression (info.node)

    flat = []
    for node in head_node.lhs:
        assignments = []
        info = VisitorInfo (node, head_node)
        _tree_visit (info, visiting_new, visitor, assignments)

        flat_count = 0 if len (assignments) <= 1 else len (assignments) - 1
        assignments.reverse()

        for i in range (0, flat_count):
            info = assignments[i]
            assert(info.node.type == '=')

            # assignment on previous statement
            copy = info.node.copy (head_node) # updates parents
            flat.append(copy)

            # update assignment with lhs of the assignment.
            dst = info.parent.lhs if info.on_lhs else info.parent.rhs
            pidx = info.idx
            dst[pidx] = info.node.lhs[0]
            dst[pidx].parent = info.parent # manual update

        flat.append(node)

    head_node.lhs = flat
#-------------------------------------------------------------------------------
def _make_key (name):
    assert(type(name) is list)
    return '$'.join (name)

def _name_from_key (key):
    # The parser passes names as a list of strings encompassing namespace and
    # var
    return key.split ('$')

class FunctionCall:
    def __init__(self, function_section, function, call_namespace):
        self.section = function_section
        self.function = function
        self.call_namespace = call_namespace
        self.instance_variable_refs = [] # variable names to pass on this call.
        #self.assignment_to_tree = assignment_tree

    def append_required_instance_variables (self, traits):
        # Fills the extra function parameters needed to emulate JSFX "instance"
        # pseudo object orientation.
        assert (type (traits) == FunctionTraits)

        if len (traits.instance) == 0 and  len (traits.inherited) == 0:
            return [] # Called function uses no namespacing. No parameters.

        variables = []
        namespace = self.call_namespace
        call_params = [_make_key([namespace, x]) for x in traits.instance]
        call_params_i = [_make_key([namespace, x]) for x in traits.inherited]
        for var in call_params + call_params_i:
            variables.append (var)
            self.instance_variable_refs.append (var)
        return variables

    def __repr__(self):
        s = self
        return f'bl:{s.section}, func:{s.function}, nspc:{s.call_namespace}, refs:{s.instance_variable_refs}'

class Sections:
    # holds JSFX section info, variables, functions and function calls, etc.
    def __init__(self):
        self.sd = {}
        self.order = []

    def add_section (self, section_name):
        if section_name in self.sd:
            assert (False) # Bug in the preprocessor?
            return
        self.sd[section_name] = {
            '_$num'     : set(), # global numeric variables
            '_$numrefs' : {}, # use of variables on other sections
            #'_$str' : set(), # strings
            '_$func'    : {}, # FunctionTraits objects indexed by function name
            '_$calls'   : {}, # FunctionCall objects indexed by node
        }
        self.order.append (section_name)
        # Add the new section to previously existing sections's variable refs
        for k, v in self.sd.items():
            if k == section_name:
                continue
            v['_$numrefs'][section_name] = set()

        # Add previously existing sections to the new section's variable refs
        if len (self.order) == 1:
            return
        first_section = self.order[0]
        self.sd[section_name]['_$numrefs'][first_section] = set()
        for k in self.sd[first_section]['_$numrefs'].keys():
            if k == section_name:
                continue
            self.sd[section_name]['_$numrefs'][k] = set()

    def get_printable(self):
        cp = deepcopy (self.sd)
        for section, _ in self.sd.items():
            del cp[section]['_$calls']
            cp[section]['_$calls'] = {}
            for node, v in self.sd[section]['_$calls'].items():
                cp[section]['_$calls'][f'<node {id(node)}>'] = v
        return cp

    def classify_variable_reference (self, section, var):
        key = _make_key (var) if type (var) is list else var

        for search_section in self.get_sections():
            if key in self.sd[search_section]['_$num']:
                if section != search_section:
                    self.sd[section]['_$numrefs'][search_section].add (key)
                return # Already present
        self.sd[section]['_$num'].add (key)

    def get_variable_references (self, to_source_section):
        res = set()
        for section, v in self.sd.items():
            if section != to_source_section:
                res |= v['_$numrefs'][to_source_section]
        return res

    def get_variables (self, section):
        return self.sd[section]['_$num']

    def get_sections (self):
        return self.order

    def add_call (self, section, node, call):
        assert (type (call) == FunctionCall)
        self.sd[section]['_$calls'][node] = call
        traits, _ = self.find_function_traits (section, call.function)
        required_variables = call.append_required_instance_variables (traits)
        for var in required_variables:
            self.classify_variable_reference (section, var)

    def find_call (self, section, node):
        for ssection in self.get_function_search_sections (section):
            call = self.sd[ssection]['_$calls'].get (node)
            if call:
                return call, ssection
        return None, None

    def add_new_function (self, section, node):
        assert (node.type == 'function')
        fd = FunctionTraits()

        assert (node.lhs[1].type == 'id_list')
        fd.parameters = [_make_key (n) for n in node.lhs[1].lhs]

        assert (node.lhs[2].type == 'modifiers')
        for modifier in node.lhs[2].lhs:
            if modifier.type == 'local':
                fd.local.update ([_make_key (n) for n in modifier.lhs])
            # Assuming working JSFX, so the global list will be filled from
            # the code.
            #elif modifier.type == 'global':
            #    fd.globals.update ([_make_key (n) for n in modifier.lhs])
            elif modifier.type == 'instance':
                fd.instance_unchecked.update(
                    [_make_key (n) for n in modifier.lhs])

        assert (node.lhs[0].type == 'identifier')
        key = _make_key (node.lhs[0].lhs)
        fdict = self.sd[section]['_$func']
        if key not in fdict:
            fdict[key] = fd
        else:
            # This might be caused by the merging of the "block" and "sample"
            # sections. A shadowed function might be present on the JSFX code.
            # pass the --no-sample-into-block-merge flag.
            raise RuntimeError(f'duplicated function: {key}.')

        return key, fd

    def find_function_traits (self, section, func):
        key = _make_key (func) if type (func) is list else func

        for ssection in self.get_function_search_sections (section):
            traits = self.sd[ssection]['_$func'].get (key)
            if traits:
                return traits, ssection
        return None, None

    def get_function_search_sections (self, section):
        search_sections = [section]
        if section != GLOBAL_Section and GLOBAL_Section in self.sd:
            search_sections.append (GLOBAL_Section)
        return search_sections

    def try_solve_call (self, caller_section, key):
        callid = _name_from_key (key)

        for i in range (len (callid)):
            funcname = _make_key (callid[i:])
            namespace = _make_key (callid[:i])
            ft, fsection = self.find_function_traits (caller_section, funcname)
            if ft is not None:
                # calls not done from a namespace get the fuction name
                # as namespace.
                namespace = namespace if namespace != '' else funcname
                return FunctionCall (fsection, funcname, namespace)

        return None # a call to something external function

class FunctionTraits:
    def __init__(self):
        self.parameters = [] # keeping order
        self.local = set()
        self.globals = [] # These will be added to the section namespace
        self.instance_unchecked = set() # what the JSFX writer wrote
        self.instance = [] # what is detected, keeping order
        self.parent_instance = []  # what is detected, keeping order (not impl)
        self.inherited = [] # inherited variables
        self.calls = {} # indexed by node

    def key_matches_on_instance_namespaces (self, key):
            if key in self.instance_unchecked:
                return True
            for v in self.instance_unchecked:
                if key.startswith (_make_key ([v, ''])): # namespacing
                    return True
            return False

    def add_variable (self, name):
        idtype = 'default' # too lazy for an enum for this

        if name[0] == 'this':
            if name[1] == '..':
                #TODO: fail if '..' appears on other places than after 'this'
                idtype = 'parent_instance'
                name = name[2:]
            else:
                idtype = 'instance'
                name = name[1:]

        key = _make_key(name)

        if idtype == 'default':
            if key in self.parameters:
                return name
            if key in self.local:
                return name
            if self.key_matches_on_instance_namespaces (key):
                if key not in self.instance:
                    self.instance.append (key)
                return name
            if key not in self.globals:
                self.globals.append (key)
            return name

        elif idtype == 'instance':
            if key not in self.instance:
                self.instance.append (key)

        elif idtype == 'parent_instance':
            # TODO: Move this error somewhere and document that most of the
            # functionality is in place
            raise NotImplementedError (".. on identifiers not implemented")
            self.parent_instance.add (key)
        return name

    def add_call (self, called, traits):
          # NOTICE: parent declarations by this.. are not implemented. My
          # intention is to avoid them.
        assert (type (called) == FunctionCall)
        assert (type (traits) == FunctionTraits)

        instance_vars = called.append_required_instance_variables (traits)
        if len (instance_vars) == 0:
            return # Function uses no namespacing

        # Extra variables required.
        if self.key_matches_on_instance_namespaces (called.call_namespace):
            # Inherited variables will be forwarded down to the caller of this
            # function (the one pointed to self). Parameters will added to this
            # function signature as passed-by-reference.
            # e.g. "x.f()" on this scope forwards down whatever f() has as
            # "x.<anything from f>"
            variable_type_list = self.inherited
        else:
            # New global variables with the name of the namespace they were
            # called from. e.g. "x.f() -> creates globals called x.<whatever>"
            #
            # Reminder, the namespace is the function name if the function was
            # called without namespace (e.g. f() ).
            #
            # Notice that on JSFX "local" variables don't participate on
            # namespacing. We don't need to check on self.local
            variable_type_list = self.globals

        for variable in instance_vars:
            if variable in variable_type_list:
                continue
            # Adding an extra parameter to pass by ref to this function.
            # Not adding the same parameters twice. E.g. on: x.f(); x.f();
            #
            # Notice that parameters can alias too, e.g. x.f(); x.y(); can
            # have both forward down a parameter called "x", so a parameter
            # is not needed twice even if it comes from different functions.
            #
            # This is exactly the reason why making structs of all the
            # instance parameters is a bad idea.
            variable_type_list.append (variable)

    def __repr__(self):
        s = self
        return f'p:{s.parameters}, loc:{s.local}, gl:{s.globals}, ins:{s.instance}, ins_u:{s.instance_unchecked}, parnt:{s.parent_instance}, inh:{s.inherited}, call:{s.calls.values()}'

def _init_jsfx_sections (head_node):
    # just making sure that each section is created before accessing
    assert (type (head_node) == Node)

    def visiting_new (info, _):
        return VisitType.NODE_FIRST

    def visitor (info, sections):
        assert (type (info) == VisitorInfo)
        if info.node.type == 'section':
            sections.add_section (info.state.section)

    sections = Sections()
    _tree_visit (VisitorInfo (head_node), visiting_new, visitor, sections)
    return sections

class DetectVariablesState:
    def __init__(self, sections):
        self.sections = sections
        self.function_key = None

#-------------------------------------------------------------------------------
def _move_functions_to_top_of_blocks (head_node, merge_block_and_samples):
    functions = {
        'block': [],
        'sample': [],
    }
    current_section = None

    for node in head_node.lhs:
        # asumming working JSFX, so functions declarations don't appear on weird
        # scopes.
        if node.type == 'section':
            current_section = node.lhs
            functions[current_section] = []

        if node.type == 'function':
            functions[current_section].append(node)

    for _, funclist in functions.items():
        for f in funclist:
            head_node.lhs.remove(f)

    if merge_block_and_samples:
        functions['block'] += functions['sample']
        functions['sample'] = []

    i = 0
    while i < len (head_node.lhs):
        node = head_node.lhs[i]
        if node.type == 'section':
            j = 1
            for func in functions[node.lhs]:
                head_node.lhs.insert(i + j, func)
                j += 1
            i += j - 1
        i += 1
#-------------------------------------------------------------------------------
def _register_functions_and_variables (sections, head_node):
    # Creates the Sections data structure, that will contain all the required
    # variables and extra parameters to pass on function calls to emulate
    # JSFX function namespacing.
    #
    # The implementation will be based on single global variables and passing
    # the extra instance parameters to functions as C++ references.
    #
    # These parameters will get stored on FunctionCall objects, stored on
    # dictionaries indexed by Node, so the code generator can easily find them.
    # Calls on the global scope are stored on the "_$calls" dictionary for each
    # section on the "Sections" object. Calls on function scope are stored on each
    # "FunctionTraits" object, under the "calls" dictionary.
    #
    # Until the previous separator (#----<till 80 chars>) all code is to achieve
    # this.
    #
    # Random notes about functions:
    #
    # -"global" is just to restrict user mistakes using globals inadvertently.
    #  I assume valid JSFX and ignore it.
    #
    # - functions can be shadowed, but there is only one set of instance
    #   variables, so the function names have to be prefixed with the section, but
    #   the variable names don't.
    #
    # -"local" variables are stateful between calls, and each section has one set
    #  of them. I will implement them as just static variables and ignore this
    #  behavior. If this becomes a problem, then one easy workaround could be
    #  to redefine every function on @init on each section and then manually
    #  remove those that are unused. TODO: add some kind of warning to detect
    #  that a function uses locals state between calls (detect if locals appear
    #  on LHS or RHS of an assignment first).
    #
    # -"instance" contains variables/namespaces that are passed down to the
    #  caller:
    #
    #  whatever.set_foo(32); // whatever.foo = 32;
    #  set_foo(32); // set_foo.foo = 32;
    #
    # -I don't know what the static keyword does.
    assert (type (sections) == Sections)
    assert (type (head_node) == Node)

    def visiting_new(info, _):
        assert (type (info) == VisitorInfo)
        if info.node.type == 'function':
            # All other variables are for the global scope, as JSFX has no
            # scopes on compound statements, conditionals and loops
            return VisitType.NODE_ONLY
        return VisitType.NODE_AFTER_LHS

    def global_visitor(info, state):
#       print(f'visited. {info}')
        assert (type (info) == VisitorInfo)
        assert (type (state) == DetectVariablesState)

        if info.node.type == 'string':
            assert(False) # TODO

        if info.node.type == 'identifier':
            if info.parent.type == 'call' and info.on_lhs:
                # identifiers on function calls are processed on the "call"
                # section, as they need resolution .e.g what is this.x.y.z(a) a
                # call to "z" from "this.x.y"? a call to "y.z" from "this.x"?
                return
            state.sections.classify_variable_reference(
                info.state.section, info.node.lhs
                )

        if info.node.type == 'call':
            identifier = info.node.lhs[0].lhs
            call = state.sections.try_solve_call(
                info.state.section, _make_key (identifier)
                )
            if call is None:
                return
            state.sections.add_call (info.state.section, info.node, call)

    def function_visitor(info, state):
        assert (type (info) == VisitorInfo)
        assert (type (state) == DetectVariablesState)

        if info.node.type == 'identifier':
            if info.parent.type == 'call' and info.on_lhs:
                # identifiers on function calls are processed on the "call"
                # section, as they need resolution .e.g what is this.x.y.z(a) a
                # call to "z" from "this.x.y"? a call to "y.z" from "this.x"?
                return
            thisfunc, _ = state.sections.find_function_traits(
                info.state.section, state.function_key
                )
            newname = thisfunc.add_variable (info.node.lhs)
            # "this." and "this.."" may get dropped from the name
            info.node.lhs = newname

        if info.node.type == 'call':
            identifier = info.node.lhs[0].lhs
            called = state.sections.try_solve_call(
                info.state.section, _make_key (identifier))
            if not called:
                # E.g. calling some JSFX function that has to be emulated
                return
            thisfunc, _ = state.sections.find_function_traits(
                info.state.section, state.function_key
                )
            assert (type(thisfunc) == FunctionTraits)
            thisfunc.calls[info.node] = called
            traits, _ = state.sections.find_function_traits(
                called.section, called.function
                )
            thisfunc.add_call (called, traits)

    state = DetectVariablesState (sections)
    # This function makes multiple "_tree_visit" calls, so we manually pass
    # the global state around
    visit_state = VisitorGlobalState()
    for node in head_node.lhs:
        if node.type == 'function':
            key, traits = sections.add_new_function (visit_state.section, node)
            state.function_key = key
            info = VisitorInfo (node.rhs[0], node, state=visit_state)
            visit_state = \
                _tree_visit (info, visiting_new, function_visitor, state)
            # manually adding the generated global variables after the function
            # has been visited.
            for globalv in traits.globals:
                sections.classify_variable_reference(
                    visit_state.section, globalv)
        else:
            info = VisitorInfo (node, head_node, state=visit_state)
            visit_state = \
                _tree_visit (info, visiting_new, global_visitor, state)

#-------------------------------------------------------------------------------
def _emulate_implicit_return_values (head_node):
    # The current implementation of implicit return values is based on making
    # a C++11 lambda on conditionals.
    #
    # This function has the side effect of converting every contitional and
    # loop content into a 'seq'.

    def make_seq_on_all_rhs_of_node (src_node):
        for node in src_node.rhs:
            if node.type == 'seq':
                # for conditionals, the code for "if" an "else" are on the rhs.
                continue
            old = deepcopy (node)
            node.reset ('seq', [old], line=old.line)

    def make_dummy_else(node):
        # Sometimes the last line of a function is a ternary that doesn't handle
        # all the "else" blocks. In that case it is most likely that the user
        # wasn't relying on the implicit return value of JSFX.
        #
        # As it isn't possible to know which value the JSFX would return in such
        # case, we emulate returning a dummy value. Notice althought very
        # unlikely, this could break some (insane) program relying on such
        # behavior.
        #
        # Returning 0.0/0.0 (NaN) signals that the user that something weird
        # was happenning on the generation. #TODO: maybe allow to add generation
        # comments...
        if node.type != 'if' or len(node.rhs) == 2:
            return

        n = Node ("value", ["0."], bottom=True)
        n = Node ("/",  [n] , [n], arithmetic=True)
        node.rhs.append (Node('seq', [n]))

    def visiting_new(info, _):
        assert (type (info) == VisitorInfo)

        retval  = VisitType.NODE_AFTER_LHS
        node_type = info.node.type
        is_loop = node_type.startswith ('loop')

        #convert every if, and loop body/branches in a seq.
        if node_type != 'if' and not is_loop :
            return retval

        make_seq_on_all_rhs_of_node (info.node)
        parent_is_seq = info.parent.type == 'seq'
        is_last_in_seq = parent_is_seq and info.parent.lhs[-1] == info.node

        type_stack = info.get_node_type_stack(4)
        # last statement in function: will need to act as return value
        add_lambda = is_last_in_seq and ['seq', 'function'] == type_stack[1:3]

        if not add_lambda and parent_is_seq and is_last_in_seq:
            # recursive lambda propagation
            add_lambda = info.node_type_seq_match (1, [
                    ['seq', 'if', 'lambda'],
                    ['seq', 'loop', 'seq', 'lambda'],
                    ['seq', 'loop-counter', 'seq', 'lambda'],
                    ['seq', 'loop-eval-result', 'seq', 'lambda'],
                ])

        if not add_lambda:
            # lambdas for 'if' will be on the parent. For for loops they have an
            # intermediate 'seq' to accomodate an extra instruction to return a
            # temporary value.
            lambda_i = 2 if is_loop else 1
            # if not hanging directly from a 'seq' it is assumed to be part
            # of an assignment, arithmetic operation, etc. Notice that
            # conditionalbranches (if and else) and loop bodies have 'seq'
            # as containers.
            add_lambda = not parent_is_seq and type_stack[lambda_i] != 'lambda'

        if not add_lambda:
            return retval

        if is_loop:
            # adding an assignment expression to LOOP_TEMP variable on the tail
            # of the loop sequence
            loop_seq = info.node.rhs[0]
            assert (loop_seq.type == 'seq')
            loop_cmds = loop_seq.lhs
            retvar = _create_identifier_node(
                LOOP_TEMP + str (type_stack.count ('lambda'))
                )

            if len (loop_cmds) > 0:
                last = loop_cmds[-1]
                if last.type == '=':
                    loop_cmds.append (Node(
                        '=', [deepcopy (retvar)], [last.lhs[0]], line=last.line
                        ))
                else:
                    old = deepcopy (last)
                    last.reset ('=', [deepcopy (retvar)], [old], line=last.line)
            # wrapping the loop on a seq with the loop and the local variable
            # identifier
            loop = deepcopy (info.node)
            seq = Node ('seq', [loop, retvar], line=loop.line)
            # Adding the seq to the lambda, just ready for having a return added
            info.node.reset(
                'lambda', [deepcopy (retvar)], [seq], line=loop.line
                )
        else:
            old = deepcopy (info.node)
            make_dummy_else (old)
            info.node.reset ('lambda', [], [old], line=old.line)

        return retval

    def visitor(info, _):
        assert (type (info) == VisitorInfo)

        if info.node.type != 'seq' or len (info.node.lhs) == 0:
            return

        add_return = info.node_type_seq_match (1, [
            ['function'],
            ['lambda'], # this is seq + lambda
            ['if', 'lambda'],
        ])
        if not add_return:
            return

        lastnode = info.node.lhs[-1]
        if lastnode.type == '=':
            info.node.lhs.append(
                Node ('return', lastnode.lhs, line=lastnode.line))
        else :
            info.node.lhs[len (info.node.lhs) - 1] = \
                Node ('return', [lastnode], line=lastnode.line)

    _tree_visit (VisitorInfo (head_node), visiting_new, visitor)

#-------------------------------------------------------------------------------
def _handle_if_assignments_on_lhs (head_node):
    # from the manual. This is valid. (a < 5 ? b : c) = 8
    #
    # This works too.
    #  (2 ? this.._x : this.._y) = 4;
    #
    # Nonsense like this compiles and do what is expected (assignment has high
    # prio):
    #  m + (0 ? (this.._x) : (x = m + 1; this.._y)) = 4;
    # Same with this:
    #  m + (0 ? (this.._x) : (x = m + 1; this.._y)) + m = 4;
    #
    # These things won't be explicitly handled here. Just assignment to an if on
    # lhs.
    def visiting_new (info, _):
        assert (type (info) == VisitorInfo)
        return VisitType.NODE_AFTER_LHS

    def visitor (info, _):
        assert (type (info) == VisitorInfo)
        # TODO: Stub. Just asserting that it doesn't happen for now. This would
        # require to return a pointers from the if branches, and to surround the
        # if lambda by *().
        if info.node.type != '=':
            return
        assert (info.node.lhs[0].type != 'if')

    _tree_visit (VisitorInfo (head_node), visiting_new, visitor)

def _use_compound_assignments (head_node):
    # Convert things like e.g. "x = x + 1" in "x += 1" Those where undone by
    # the parser.

    compound_ops = "+-*/&|%";

    def visiting_new (info, _):
        assert (type (info) == VisitorInfo)
        if info.node.type == '=':
            return VisitType.NODE_ONLY
        else:
            return VisitType.NODE_FIRST

    def visitor (info, _):
        assert (type (info) == VisitorInfo)
        if info.node.type != '=':
            return
        rhs = info.node.rhs[0]
        if rhs.type not in compound_ops:
            return
        if str (info.node.lhs[0]) != str (rhs.lhs[0]):
            return

        info.node.type = rhs.type + '='
        info.node.rhs = rhs.rhs

    _tree_visit (VisitorInfo (head_node), visiting_new, visitor)

#-------------------------------------------------------------------------------
def optimize_away():
    # echo "(y + 4) = z;" | ./eel2c.py --mode ast
    #
    # This is "y + 4; y = z". If an expression has no assignment or call it is
    # dead
    pass
#-------------------------------------------------------------------------------
def check_broken_lhs():
    #echo "(y + 4 + x) = z;" | ./eel2c.py --mode ast
    # TODO This is accepted without compiler error
    pass
#-------------------------------------------------------------------------------
def _adapt_some_eel2_operators_to_cpp_calls (head_node):
    # Some JSFX operators are implemented as function calls, e.g. == and !=
    # which do approximate comparisons for doubles. The "jsfx_" functions
    # themselves are defined on "_generate_runtime_environment".
    operation_map = {
        '==_': 'eel2_eq',
        '!=_': 'eel2_ne',
        '^': 'eel2_pow',
        '<<': 'eel2_lshift',
        '>>': 'eel2_rshift',
        '|': 'eel2_or',
        '&': 'eel2_and',
        '~': 'eel2_xor',
    }
    def visiting_new (info, _):
        assert (type (info) == VisitorInfo)
        return VisitType.NODE_AFTER_LHS

    def visitor (info, opmap):
        assert (type (info) == VisitorInfo)
        # Transform any operator on "operation_map" to a call
        jsfx_func = opmap.get (info.node.type)
        if jsfx_func is None:
            return
        id_node = _create_identifier_node (jsfx_func, info.node.line)
        info.node.type = 'call'
        lhs = info.node.lhs[0]
        rhs = info.node.rhs[0]
        info.node.lhs = [id_node]
        info.node.rhs = [lhs, rhs]

    _tree_visit (VisitorInfo (head_node), visiting_new, visitor, operation_map)
#-------------------------------------------------------------------------------
def _generate_runtime_environment():
    # Helpers for the eel language, these functions are substituting JSFX
    # operators on the "_adapt_eel2_operators"
    lib_funcs = {}

    lib_funcs['eel2_eq'] = LibraryFunction ('eel2_eq', ['cmath'], [], '''
static double eel2_eq (double lhs, double rhs)
{
    return (double) (std::fabs (lhs - rhs) < 0.00001);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_ne'] = LibraryFunction ('eel2_ne', [], ['eel2_eq'], '''
static bool eel2_ne (double lhs, double rhs)
{
    return !eel2_eq (lhs, rhs);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_pow'] = LibraryFunction ('eel2_pow', ['cmath'], [], '''
static double eel2_pow (double lhs, double rhs)
{
    return std::pow (lhs, rhs);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_rshift'] = \
        LibraryFunction ('eel2_rshift', ['cstdint'], [], '''
static double eel2_rshift (double lhs, double rhs)
{
    return (double)((uint32_t) lhs >> (uint32_t) rhs);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_lshift'] = \
        LibraryFunction ('eel2_lshift', ['cstdint'], [], '''
static double eel2_lshift (double lhs, double rhs)
{
    return (double)((uint32_t) lhs << (uint32_t) rhs);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_or'] = LibraryFunction ('eel2_or', ['cstdint'], [], '''
static double eel2_or (double lhs, double rhs)
{
    return (double)((uint64_t) lhs | (uint64_t) rhs);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_and'] = LibraryFunction ('eel2_and', ['cstdint'], [], '''
static double eel2_and (double lhs, double rhs)
{
    return (double)((uint64_t) lhs & (uint64_t) rhs);
}
'''.replace ('\n', '')
    )

    lib_funcs['eel2_xor'] = LibraryFunction ('eel2_xor', ['cstdint'], [], '''
static double eel2_xor (double lhs, double rhs)
{
    return (double)((uint32_t) lhs ^ (uint32_t) rhs);
}
'''.replace ('\n', '')
    )

    # From jsfx ----------------------------------------------------------------
    lib_funcs['memset'] = LibraryFunction ('jsfx_memset', ['cstring'], [], '''
void jsfx_memset (double idx, double val, double size)
{{
    std::memset (&{mem}[(size_t) idx], (int) val, (size_t) size);
}}
'''.format (mem=STATIC_MEM_ARRAY).replace ('\n', '')
    )

    lib_funcs['memcpy'] = LibraryFunction ('jsfx_memcpy', ['cstring'], [], '''
void jsfx_memcpy (double idx, double val, double size)
{{
    std::memcpy (&{mem}[(size_t) dst], &{mem}[(size_t) src], (size_t) size);
}}
'''.format (mem=STATIC_MEM_ARRAY).replace ('\n', '')
    )

    header = [f'''
/* "{STATIC_MEM_ARRAY}" emulates the JSFX per instance memory pool.
It can be removed if unused. On most cases the length of this array can be
reduced. It is set to a very conservative (high) value matching what JSFX
provides. */
double {STATIC_MEM_ARRAY}[8 * 1024 * 1024] = {{}};
''']
    return header, lib_funcs
#-------------------------------------------------------------------------------
class KnownNode(Enum):
    DOWN      = 1,
    AFTER_RHS = 2,
    UP        = 3,

class CodeSection:
    def __init__ (self):
        self.chunks = { "main": []}
        self.order = []

    def add_function (self, name):
        self.order.append (name)
        self.chunks[name] = []

    def get_code (self, name=None):
        if name is None:
            return self.chunks['main']
        else:
            return self.chunks[name]

    def get_functions (self):
        return self.order

class CodegenContext:
    def __init__ (self, sections, all_funcs):
        self.code = {} # code chunks
        self.know_nodes = {}
        self.section = 'invalid'
        self.sections = sections
        self.function_traits = None
        self.current_function = None
        self.all_funcs = all_funcs # dict of LibraryFunction
        self.used_funcs = set() # hits on "all_funcs" (functions used)
        self.generation_cpp_headers = set()

    def add_code (self, chunks):
        code = chunks if type(chunks) is list else [chunks]
        assert (type(chunks) != Node)
        codelist = self.code[self.section].get_code (self.current_function)
        codelist += code

    def enter_section (self, section):
        self.section = section
        if section not in self.code:
            self.code[section] = CodeSection()

    def enter_new_function (self, name):
        assert (self.current_function == None)
        self.current_function = name
        self.code[self.section].add_function (name)

    def leave_function (self, name):
        assert (self.current_function == name)
        self.current_function = None

def _generate_cpp (ast, codegen_context):
    # Code generation pass. Use clang format or some formatter on it, it
    # doesn't try to care on how beautiful the code is.
    def visiting_new (info, _):
        assert (type (info) == VisitorInfo)
        manually_handled = [
            'if',
            'function',
            'call',
            'pow',
            '[]',
            'seq',
            'lambda',
            'loop',
            'loop-eval-result',
            'loop-counter',
            'parameter_pack',
            ]
        if info.node.type in manually_handled:
            return VisitType.NODE_ONLY

        elif info.node.type == 'return':
            return VisitType.NODE_FIRST

        # Node types where the node type string is the same than the final
        # rendering, e.g. (e.g. '+', '-', '=', ...).
        return VisitType.NODE_ALL

    def visit_branch (node, parent, state, parent_info):
        _tree_visit(
            VisitorInfo (node, parent, parent_info=parent_info),
            visiting_new,
            visitor,
            state
            )

    def visitor (info, state):
        assert (type (info) == VisitorInfo)
        assert (type (state) == CodegenContext)

        if info.node.type == 'section':
            # This code does many manual calls of the visitor, so it keeps
            # track of the current section by itself.
            state.enter_section (info.node.lhs)
            return

        if info.node.is_bottom:
            # TODO handle string
            if info.node.type == 'identifier':
                v = _get_identifier_key (info.node)
            elif info.node.type == 'string_literal':
                v = f'0.; /* jsfx2cpp strings unsupported: was: {info.node.lhs} */'
            else:
                v = info.node.lhs[0]
            state.add_code (v)
            return

        if info.node.type == 'lambda':
            state.add_code ('[&]{')
            if len (info.node.lhs) == 1:
                identifier = info.node.lhs[0]
                localvar = _get_identifier_key (identifier)
                state.add_code (f'double {localvar} = {{}}; ')

            visit_branch (info.node.rhs[0], info.node, state, info)
            state.add_code ('}()')
            return

        if info.node.type == 'if':
            state.add_code ('if (')
            visit_branch (info.node.lhs[0], info.node, state, info)
            state.add_code (') {')
            visit_branch (info.node.rhs[0], info.node, state, info)
            state.add_code ('}')
            if len (info.node.rhs) == 2:
                state.add_code ('else {')
                visit_branch (info.node.rhs[1], info.node, state, info)
                state.add_code ('}')
            return

        if info.node.type == 'function':
            f = info.node
            # prepending the section
            fname = _make_key(f.lhs[0].lhs)
            fname_final = _make_key ([state.section, fname])
            state.enter_new_function (fname_final)
            state.add_code (f'double {fname_final}')
            # parameters
            state.add_code ('(')

            id_list = f.lhs[1]
            assert (id_list.type == 'id_list')
            traits, _ = \
                state.sections.find_function_traits (state.section, fname)
            assert (traits is not None)
            local_params     = ['double ' + p[0] for p in id_list.lhs]
            inherited_params = traits.instance + traits.inherited
            inherited_params = ['double& ' + p for p in inherited_params]
            parameters = local_params + inherited_params
            csv = [','] * (len (parameters) * 2 - 1)
            csv[0::2] = parameters
            state.add_code (csv)
            state.add_code (') {')

            for local in traits.local:
                state.add_code (f'double {local} = 0.;')

            state.function_traits = traits
            visit_branch (f.rhs[0], info.node, state, info)
            state.function_traits = None

            state.add_code ('}')
            state.leave_function (fname_final)
            return

        if info.node.type == 'seq':
            no_semicolon = [
                'function',
                'loop',
                'loop-eval-result',
                'loop-counter',
                'if',
                'section'
            ]
            last = len (info.node.lhs) - 1
            for idx, node in enumerate (info.node.lhs):
                ninfo = VisitorInfo(
                    node, on_lhs=True, idx=idx, last=last, parent_info=info
                    )
                _tree_visit (ninfo, visiting_new, visitor, state)
                if node.type not in no_semicolon:
                    state.add_code (';')
            return

        if info.node.type == 'return':
            state.add_code ('return')
            return

        if info.node.type == 'call':
            if state.function_traits is None:
                # call on global scope
                call, _ = state.sections.find_call (state.section, info.node)
            else:
                # call made from inside a function
                call = state.function_traits.calls.get (info.node)

            if call is None:
                # call to some function not defined on this JSFX e.g. "memset"
                identifier = _make_key (info.node.lhs[0].lhs)
                libcall = state.all_funcs.get (identifier)
                if libcall is not None:
                    state.used_funcs.add (identifier);
                    identifier = libcall.cppfunc
                state.add_code (f'{identifier} (')
            else:
                state.add_code (f'{_make_key([call.section, call.function])} (')

            expr_last = len (info.node.rhs) - 1
            for idx, expr in enumerate (info.node.rhs):
                info = VisitorInfo (expr, info.node, parent_info=info)
                _tree_visit (info, visiting_new, visitor, state)
                if idx != expr_last:
                    state.add_code (',')

            if call is not None:
                extra = call.instance_variable_refs
                if len (extra) > 0:
                    if expr_last >= 0:
                        state.add_code (',')
                csv = [','] * (len (extra) * 2 - 1)
                csv[0::2] = extra
                state.add_code (csv)

            state.add_code (')')
            if call is None and libcall is None:
                # call to unknown external function
                state.add_code ('/*TODO: unknown call */')
            return

        if info.node.type == 'pow':
            state.add_code ('pow (')
            visit_branch (info.node.lhs[0], info.node, state, info)
            state.add_code (',')
            visit_branch (info.node.rhs[0], info.node, state, info)
            state.add_code (')')
            return

        if info.node.type == '[]':
            state.add_code (f'{STATIC_MEM_ARRAY}[(size_t)(')
            lhs = info.node.lhs[0]
            assert(lhs.type != 'identifier' or lhs.lhs[0] != 'gmem') #not impl
            visit_branch (lhs, info.node, state, info)
            val = 1
            rhs_type = info.node.rhs[0].type
            if rhs_type == 'value':
                val = int (float (info.node.rhs[0].lhs[0]))

            if val == 0:
                state.add_code (')]')
            elif rhs_type == 'identifier' or rhs_type == 'value':
                state.add_code (' + ')
                visit_branch (info.node.rhs[0], info.node, state, info)
                state.add_code (')]')
            else:
                state.add_code ('+ (')
                visit_branch (info.node.rhs[0], info.node, state, info)
                state.add_code ('))]')
            return

        if info.node.type == 'call-x2':
            assert(False) # what is this?
            return

        if info.node.type in ['loop-counter', 'loop']:
            state.generation_cpp_headers.add ('algorithm') # for std::max
            idx = info.get_node_type_stack().count ('loop-counter')
            idx = '' if idx == 1 else str (idx)
            counter_hdr = f'for (int $$i{idx} = 0, $$end{idx} = std::max (0, (int) ('
            header = {
                'loop-counter': counter_hdr,
                'loop': 'while (',
            }
            middle = {
                'loop-counter': f')); $$i{idx} < $$end{idx}; ++$$i{idx}) {{',
                'loop': ') {',
            }
            state.add_code (header[info.node.type])
            visit_branch (info.node.lhs[0], info.node, state, info)
            state.add_code (middle[info.node.type])
            visit_branch (info.node.rhs[0], info.node, state, info)
            state.add_code ('}')
            return

        if info.node.type == 'loop-eval-result':
            seq = info.node.rhs[0]
            assert (seq.type == 'seq')
            if len (seq.lhs) == 0:
                return

            idx = info.get_node_type_stack().count ('loop-eval-result')
            var = '$$cond'
            if idx > 1:
                var += str (idx)
            state.add_code (f'{{ bool {var}; do {{ {var} = (bool)[&]{{')
            # Adding an in-place return to handle the bool assignment
            cp_seq = deepcopy (seq) # No AST modification. Copy.
            last = cp_seq.lhs[-1]
            if last.type == '=':
                cp_seq.lhs.append (Node ('return', [last.lhs]))
            else:
                retval = deepcopy (last)
                last.reset ('return', [retval])

            visit_branch (cp_seq, info.node, state, info)
            state.add_code (f'}}();}} while ({var}); }}')
            return

        # The remaining types have a matching string on "node.type" with its C++
        # operator, e.g. the arithmetic ones (+, -, ...), so they are visited
        # down and then on the way up from lhs to rhs the "node.type" is printed
        # (except for the unaries, that are kept here to share the parentheses
        # handling).
        ntype = info.node.type
        unaries = ['!', 'MINUS']

        if info.node not in state.know_nodes:
            # Down visit. Node first appearing
            state.know_nodes[info.node] = KnownNode.DOWN

            if ntype in unaries:
                state.add_code (ntype if ntype != 'MINUS' else '-')

            if info.node.has_parentheses == True:
                state.add_code ('(')
            return

        if state.know_nodes[info.node] is KnownNode.AFTER_RHS:
            # Up visit. leaving Node
            state.know_nodes[info.node] = KnownNode.UP
            if info.node.has_parentheses == True:
                state.add_code (')')
            return

        # Visit transition from the lhs up down the to rhs
        state.know_nodes[info.node] = KnownNode.AFTER_RHS
        state.add_code (ntype if ntype not in unaries else '')
        #end of visitor inner function

    _tree_visit (VisitorInfo (ast), visiting_new, visitor, codegen_context)

    return codegen_context.code, \
           codegen_context.used_funcs, \
           codegen_context.generation_cpp_headers
#-------------------------------------------------------------------------------
class SectionVariables:
    def __init__ (self, variables, external_refs):
        self.local = set()
        self.glbal = set() # python reserves words in a very annoying way
        self.unclassified = set (variables)
        self.refs = external_refs

    def finished_classifying(self):
        self.glbal |= self.unclassified
        self.unclassified = None

class ClassifiedVariables:
    def __init__ (self, sections):
        assert (type (sections) == Sections)
        self.vars = {}
        for name in sections.get_sections():
            self.vars[name] = SectionVariables(
                sections.get_variables (name),
                sections.get_variable_references (name)
                )

def _classify_variable_scope (head_node, sections):
    # Detect if variables hold state between calls of the same section, so they
    # can't be placed as local variables on a function. As of now every global
    # variable used from inside a function is considered stateful. Functions
    # are not analyzed (it is perfectly possible to do, just not done at this
    # stage because a correct usage of "local" by the JSFX dev is assumed).


    #TODO: maybe detect constants. AKA values set once to a "value" on all
    # sections

    def visiting_new (info, _):
        if info.node.type == 'function':
            return VisitType.NODE_ONLY
        else:
            return VisitType.NODE_FIRST

    def visitor (info, classify):
        assert (type (info) == VisitorInfo)
        assert (type (classify) == ClassifiedVariables)

        if info.node.type != 'identifier':
            return

        var = _make_key (info.node.lhs)
        secvars = classify.vars.get (info.state.section)
        if secvars is None:
            assert (False) # BUG!
            return

        if var not in secvars.unclassified:
            # Either a function or an already classified variable
            return

        if info.parent.type == '=' and info.on_lhs and var not in secvars.refs:
            # Notice that this step is unnaffected by the order of compound
            # statement optimization, as x += 1 reads "x" before setting it, so
            # no classification error happens.
            #
            # Still the variable can appear on both sides of the assignment,
            # e.g. "x = y + x"
            def has_var (qinfo):
                if qinfo.node.type != 'identifier':
                    return False
                return _make_key (qinfo.node.lhs) == var

            has_var_on_rhs = _query (info.parent.rhs[0], has_var)
            if len (has_var_on_rhs) != 0 or info.parent.rhs[0].is_arithmetic:
                # appears on the left hand side of an assignment: has memory
                secvars.glbal.add (var)
            else:
                secvars.local.add (var)
        else:
            secvars.glbal.add (var)
        secvars.unclassified.discard (var)

    classify_state = ClassifiedVariables (sections)
    _tree_visit (VisitorInfo (head_node), visiting_new, visitor, classify_state)

    for v in classify_state.vars.values():
        v.finished_classifying()

    return classify_state
#-------------------------------------------------------------------------------
JSFX_SPECIAL_VAR_SCHEMA = {
    'type': 'object',
    'properties' : {
        'plain': {
            'type': 'object',
            'additionalProperties': {
                '$ref': '#/definitions/entry'
            }
        },
        'regex': {
            'type': 'object',
            'additionalProperties': {
                '$ref': '#/definitions/entry'
            }
        },
        'additionalProperties': False,
    },
    'required': ['plain', 'regex'],
    'definitions': {
        'entry': {
            'type': 'object',
            'properties' : {
                'sections': {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                        'enum': [
                            'all',
                            'init',
                            'slider',
                            'block',
                            'sample',
                            'gfx',
                            'serialize'
                            ]
                    }
                },
                'access' : {
                    'type': 'string',
                    'enum': ['r', 'w', 'rw']
                },
            },
            'additionalProperties': False,
            'required': ['sections', 'access']
        }
    }
}
#-------------------------------------------------------------------------------
class JSFXSpecialVariable:
    def __init__(self, sections, access):
        self.access = access
        self.sections = sections

    def matches (self, section, var_is_read):
        sects = self.sections
        match = section in sects or len (sects) == 0 or sects[0] == 'all'
        read_access = self.access == 'r'
        return match and self.access == 'rw' or read_access == var_is_read

class JSFXSpecialVariables:
    def __init__(self, dic):
        self.plain = {}
        self.regex = {}
        jsonschema.validate (instance=dic, schema=JSFX_SPECIAL_VAR_SCHEMA)
        for k, v in dic['plain'].items():
            self.plain[k] = JSFXSpecialVariable (v['sections'], v['access'])
        for k, v in dic['regex'].items():
            self.plain[k] = JSFXSpecialVariable (v['sections'], v['access'])

def _parse_jsfx_special_variables (filename):
    with open (filename, 'r') as f:
        content = f.read()
    return JSFXSpecialVariables (json.loads (content))

class ReplaceJsfxSpecialVariablesState:
    def __init__ (self, variables):
        assert (type (variables) == JSFXSpecialVariables)
        self.vars = variables
        self.funcs = {}

def _replace_jsfx_special_variables_by_stub_calls (head_node, special_vars):
    assert (type (head_node) == Node)
    assert (type (special_vars) == JSFXSpecialVariables)
    # LibraryFunction

    def visiting_new (info, _):
        assert (type (info) == VisitorInfo)
        return VisitType.NODE_FIRST

    def visitor (info, state):
        assert (type (info) == VisitorInfo)
        assert (type (state) == ReplaceJsfxSpecialVariablesState)

        if info.node.type != 'identifier' or \
            (info.node.type == 'identifier' and info.parent.type == 'function'):
            # ignoring function identifiers. "id_lists" on functions (the lists)
            # with function parameters and modifiers) are nodes with
            # "bottom=True", so the visitor stops iteration at them. Those are
            # covered by "info.node.type != 'identifier'"
            return

        var = _make_key (info.node.lhs)
        specvar = state.vars.plain.get (var)
        if specvar is None:
            for k, v in state.vars.regex.items():
                if re.match (k, var):
                    specvar = v
                    break
        if specvar is None:
            return

        writing = _is_identifier_assigned (info)
        match = specvar.matches (info.state.section, not writing)
        if not match:
            return

        #TODO: not considering shadowing of JSFX special variables in function
        # parameters, by e.g. local variables, etc. I don't even know if that's
        # an issue on the real JSFX, this is just not investigated for now.
        funcname = f'jsfx_specialvar_{"set" if writing else "get"}_{var}'
        if funcname not in state.funcs:
            set_def = f'''
void {funcname} (double val) {{
    /* TODO: stub for setting JSFX var "{var}" */
}}
'''
            set_def.replace ('\n', '')
            get_def = f'''
double {funcname}() {{
    return 0.; /* TODO: stub for getting JSFX var "{var}" */
}}
'''
            get_def.replace ('\n', '')
            state.funcs[funcname] = LibraryFunction(
                funcname, [], [], set_def if writing else get_def
                )
        _replace_identifier_by_function_call (info, funcname, writing)

    state = ReplaceJsfxSpecialVariablesState (special_vars)
    _tree_visit (VisitorInfo (head_node), visiting_new, visitor, state)
    return state.funcs
#-------------------------------------------------------------------------------
LIBFUNC_SCHEMA = {
    'type': 'object',
    'additionalProperties': {
        'type': 'object',
        'properties': {
            'to': {
                'type': 'string',
            },
            'headers': {
                '$ref': '#/definitions/stringlist'
            },
            'definition' : {
                  'anyOf': [
                    { 'type': 'string' },
                    { '$ref': '#/definitions/stringlist' }
                  ],
            },
            'dependencies' : {
                '$ref': '#/definitions/stringlist'
            },
        },
        'additionalProperties': False,
        'required': ['to'],
    },
    'definitions': {
        'stringlist': {
            'type': 'array',
            'items': {
                'type': 'string',
            }
        },
    },
}
#-------------------------------------------------------------------------------
class LibraryFunction:
    def __init__(
        self,
        cpp,
        headers=None,
        dependencies=None,
        definition=None
        ):
        self.cppfunc = cpp
        self.headers = headers
        self.dependencies = dependencies
        self.definition = definition
#-------------------------------------------------------------------------------
def _append_external_library_functions (lib_funcs, libfunc_files):
    # Add the user passed json files describing JSFX function mappings to
    # the dictionary of recognized functions
    for filename in libfunc_files:
        with open (filename, 'r') as f:
            content = f.read()
        dic = json.loads (content)
        jsonschema.validate (instance=dic, schema=LIBFUNC_SCHEMA)

        for k, v in dic.items():
            # external overriding of builtins is possible
            defin = v.get ("definition")
            if type (defin) == list:
                defin = ' '.join (defin)

            lib_funcs[k] = LibraryFunction(
                v["to"],
                v.get ("headers"),
                v.get ("dependencies"),
                defin
                )
#-------------------------------------------------------------------------------
def _generate_function_call_headers(
    lib_funcs, slider_funcs, specialvar_funcs, used_funcs, extra_headers
    ):
    funcs = []
    # Fixing function dependencies on other functions. To keep things simple
    # just one level of dependency is allowed now. Nothing more than that is
    # at the time of writing this.
    for f in used_funcs:
        if f not in lib_funcs:
            continue
        depens = lib_funcs[f].dependencies
        for depen in (depens or []):
            if depen not in funcs:
                funcs.append (depen)

    # making sure that the dependencies are declared first.
    for f in used_funcs:
        if f not in lib_funcs:
            continue
        if f not in funcs:
            funcs.append (f)

    header_names = set (extra_headers)
    headers = ["// includes for environment function calls\n"]
    definitions = ["// definitions for environment function calls\n"]

    for f in sorted (funcs):
        hdrs = lib_funcs[f].headers
        defin = lib_funcs[f].definition
        for hdr in (hdrs or []):
            header_names.add (hdr)
        if defin is not None:
            definitions.append (defin)

    def add_stubs(comment, stubs, used_funcs):
        # ignoring headers on stubs
        ret = [comment]
        for f in sorted (used_funcs):
            lf = stubs.get (f)
            if lf is not None:
                # no check for headers. This is generated here and there aren't.
                # no check to see if there is a definition. Same rationale.
                ret.append (lf.definition)
        return ret

    sliders = add_stubs ("// stubs for sliders\n", slider_funcs, used_funcs)
    specialvars = add_stubs(
        "// stubs for JSFX special variables\n", specialvar_funcs, used_funcs
        )
    headers += [f'#include <{v}>\n' for v in sorted (header_names)]
    return headers, definitions + ['\n'], sliders, specialvars
#-------------------------------------------------------------------------------
def _generate_class_file(
    section_order,
    external_header,
    global_runtime,
    lib_funcs,
    slider_funcs,
    specialvar_funcs,
    used_funcs,
    extra_headers,
    classified_variables,
    code
    ):

    def add_separator (arr):
        arr += ['\n    //' + '-' * 76 + '\n']

    assert (type (classified_variables) == ClassifiedVariables)
    ret = ['#pragma once\n']
    ret += ['// Generated by jsfx2cpp.py. To be manually corrected.\n']
    headers, runtime, sliders, specialvar = _generate_function_call_headers(
        lib_funcs, slider_funcs, specialvar_funcs, used_funcs, extra_headers
        )

    ret += headers
    ret += external_header

    ret += ['struct jsfx_process {']
    add_separator (ret)
    ret += global_runtime
    add_separator (ret)
    ret += runtime
    add_separator (ret)
    ret += specialvar
    add_separator (ret)
    ret += sliders
    for section in section_order:
        newvars = []
        for var in classified_variables.vars[section].glbal:
            newvars.append (var)

        if section == GLOBAL_Section:
            # All variables on init are global
            for var in sorted(classified_variables.vars[section].local):
                newvars.append (var)

        if len (newvars) == 0:
            continue

        add_separator (ret)
        ret += [f'// global/stateful variables for section "{section}"\n']
        ret += [f'double {v};' for v in sorted (newvars)]
        add_separator (ret)
        ret += [f'void init_{section}_variables()\n{{']
        ret += [f'{v} = 0;' for v in sorted (newvars)]
        ret += [f'}}']

    add_separator (ret)
    ret += ['jsfx_process() {jsfx_process_reset();}\n']
    for section in section_order:
        add_separator (ret)
        funcname = "jsfx_process_reset" if section == GLOBAL_Section else section
        ret += [f'void {funcname}(){{']
        if section != GLOBAL_Section:
            # local variables, except on init
            for var in sorted (classified_variables.vars[section].local):
                ret += [f'double {var} = 0.;']

        cb = code[section]
        assert (type (cb) == CodeSection)
        ret += cb.get_code()
        ret += ['}']

    for section in section_order:
        fns = []
        cb = code[section]
        assert (type (cb) == CodeSection)

        for func in sorted (cb.get_functions()):
            add_separator (fns)
            fns += cb.get_code (func)

        if len (fns) > 0:
            ret += [f'\n// functions for section "{section}"\n']
            ret += fns

    ret += ['}; /* jsfx_process */ ']
    return ' '.join (ret)
#-------------------------------------------------------------------------------
class Slider:
    def __init__(self, code):
        def do_raise():
            raise RuntimeError(f'invalid slider format: {code}')

        # ignoring  .wav, .txt, .ogg, or .raw files scan sliders for now
        # https://www.reaper.fm/sdk/js/js.php#js_file
        # e.g.
        # slider1:0<-100,6,1>Wet Mix (dB)
        # slider1:wet_db=-12<-60,12>-Wet (dB)
        # slider8:0,Output frequency (Hz)
        remainder = code.strip().split (':')
        if len (remainder) == 2:
            self.id = remainder[0].strip()
        else:
            do_raise()

        remainder = remainder[1].strip().split ('=')
        if len (remainder) == 1:
            self.var = self.id
        elif len (remainder) == 2:
            self.var = remainder[0].strip()
            remainder = [remainder[1].strip()]
        else:
            do_raise()

        self.min = 0.0
        self.max = 1.0
        self.step = None

        if '<' not in code:
            # slider8:0,Output frequency (Hz)
            remainder = remainder[0].strip().split (',')
            self.default = float (remainder[0])
            self.description = remainder[1].strip()
            self.hidden = self.description.startswith ('-')
            return

        remainder = remainder[0].strip().split ('<')
        if len (remainder) == 2:
            self.default = float(remainder[0].strip())
        else:
            do_raise()

        remainder = remainder[1].strip().split ('>')
        if len (remainder) == 2:
            self.description = remainder[1].strip()
            self.hidden = self.description.startswith ('-')
        else:
            do_raise()

        remainder = remainder[0].strip().split ('{')
        remainder = remainder[0].strip() # ignoring label specifications
        remainder = remainder.split (',')

        if len (remainder) >= 1 and remainder[0] != '':
            self.min = float (remainder[0])
        if len (remainder) >= 2 and remainder[1] != '':
            self.max = float (remainder[1])
        if len (remainder) >= 3 and remainder[2] != '':
            self.step = float (remainder[2])
        if len (remainder) >= 4:
            do_raise()
#-------------------------------------------------------------------------------
def _parse_slider_code_section (slider_section_code):
    slider_funcs = {}
    sliders = {}
    for line in slider_section_code:
        slider = Slider (line)
        sliders[slider.var] = slider

    for name in sliders.keys():
        sld = sliders[name]
        fname = f'get_slider_{name}'
        libfunc = LibraryFunction (fname, [], [], f'''
double {fname}() {{
// TODO: stub, add code for getting "{name}"
// Range: min:{sld.min}, max:{sld.max}, default: {sld.default}, step: {sld.step}
return 0.;
}}
        '''
        )
        slider_funcs[fname] = libfunc

        fname = f'set_slider_{name}'
        libfunc = LibraryFunction (fname, [], [], f'''
void {fname} (double v) {{
// TODO: stub, add code for setting "{name}"
// Range: min:{sld.min}, max:{sld.max}, default: {sld.default}, step: {sld.step}
}}
        '''
        )
        slider_funcs[fname] = libfunc
    return sliders, slider_funcs

#-------------------------------------------------------------------------------
def _is_identifier_assigned (info):
    assert (info.node.type == 'identifier')
    return info.parent.type == '=' and info.on_lhs
#-------------------------------------------------------------------------------
def _replace_identifier_by_function_call (info, functioname, writing):
    assert (info.node.type == 'identifier')
    id_node = _create_identifier_node (functioname, info.node.line)
    if writing:
        assert (_is_identifier_assigned (info))
        rhs = info.parent.rhs
        info.parent.reset ('call', [id_node], rhs, line=info.node.line)
        # Not touching "info.node" to avoid breaking the visit, as it was an
        # identifier it stops here.
    else:
        info.node.reset ('call', [id_node], [], line=info.node.line)
#-------------------------------------------------------------------------------
def _replace_slider_variables_by_stub_calls (head_node, sliders):
    def visiting_new (info, _):
            return VisitType.NODE_FIRST

    def visitor (info, sliders):
        assert (type (info) == VisitorInfo)

        if info.node.type != 'identifier':
            return
        var = _make_key (info.node.lhs)
        if var not in sliders:
            return

        writing = _is_identifier_assigned (info)
        prefix = 'set' if writing else 'get'
        function = f'{prefix}_slider_{sliders[var].var}'
        _replace_identifier_by_function_call (info, function, writing)

    _tree_visit (VisitorInfo (head_node), visiting_new, visitor, sliders)
#-------------------------------------------------------------------------------
class MergeBlockAndSampleState:
    def __init__ (self):
        self.block_start = None
        self.sample_start = None
        self.block_end = None
        self.curr_idx = 0

def _merge_block_and_sample_sections (ast):
    # merges the block and sample sections, this is done just to maximize the
    # amount of variables into local function parameters, which are subject to
    # C++ register optimization.
    #
    # It assumes that the 'sample' section appears after 'block'

    assert (ast.type == 'seq')

    seq = ast.lhs
    block_start = None
    block_end = None
    sample_start = None
    sample_end = None

    for i, node in enumerate (seq):
        if node.type != 'section':
            continue
        blockname = node.lhs

        if block_start is not None and block_end is None:
            block_end = i

        if sample_start is not None and sample_end is None:
            sample_end = i

        if blockname == 'block':
            block_start = i
        elif blockname == 'sample':
            sample_start = i

    if sample_start is None:
        return # nothing to do, no 'sample' section

    if sample_end is None:
        sample_end = len (ast.lhs)

    loop_body = seq[sample_start + 1:sample_end]
    block_length =  _create_identifier_node ('$$block_length')
    spl0 =  _create_identifier_node ('spl0')
    spl1 =  _create_identifier_node ('spl1')
    samplesblock =  _create_identifier_node ('samplesblock')
    zero = Node ("value", ["0."], bottom=True)
    spl0_assign = Node ("=", [spl0], [zero])
    spl1_assign = Node ("=", [spl1], [zero])
    block_length_assign =  Node ("=", [block_length], [samplesblock])
    seq_node = Node ('seq', [spl0_assign, spl1_assign] + loop_body)
    loop = Node ('loop-counter', [block_length], [seq_node])

    if block_start is None:
        # no 'block' section, change the sample section to be the block
        assert (seq[sample_start].type == 'section')
        seq[sample_start].lhs = 'block'
        rm_start = sample_start + 1
        block_start = sample_start
        block_end = rm_start
    else:
        rm_start = sample_start

    del seq[rm_start:sample_end]
    seq.insert (block_end, loop)
    seq.insert (block_start + 1, block_length_assign)

#-------------------------------------------------------------------------------
def generate(
    ast,
    libfunc_files,
    special_vars_file,
    slider_section_code,
    merge_block_and_samples=True # might shadow functions
    ):
    assert (ast.type == 'seq')

    runtime_header, lib_funcs = _generate_runtime_environment()
    sliders, slider_funcs = _parse_slider_code_section (slider_section_code)
    _append_external_library_functions (lib_funcs, libfunc_files)
    _move_functions_to_top_of_blocks (ast, merge_block_and_samples)
    if merge_block_and_samples:
        _merge_block_and_sample_sections (ast)
    _adapt_some_eel2_operators_to_cpp_calls (ast)
    _flatten_multiple_assignments_in_expression (ast)
    specialvars = _parse_jsfx_special_variables (special_vars_file)
    specvar_funcs = \
        _replace_jsfx_special_variables_by_stub_calls (ast, specialvars)
    _replace_slider_variables_by_stub_calls (ast, sliders)
    sections =_init_jsfx_sections (ast)
    _register_functions_and_variables (sections, ast)
    _emulate_implicit_return_values (ast)
    _handle_if_assignments_on_lhs (ast)
    _use_compound_assignments (ast)

    # TODO: detect constants?
    # TODO: chainded if else statements that can be substituted by a switch?

    #Generation steps, no more AST manipulation
    classified_variables = _classify_variable_scope (ast, sections)
    all_funcs = {**lib_funcs, **slider_funcs, **specvar_funcs}
    code_sections, used_funcs, extra_headers = _generate_cpp(
        ast, CodegenContext (sections, all_funcs)
        )
    text = _generate_class_file(
        sections.get_sections(),
        [f'// {s}\n' for s in slider_section_code],
        runtime_header,
        lib_funcs,
        slider_funcs,
        specvar_funcs,
        used_funcs,
        extra_headers,
        classified_variables,
        code_sections
        )
    return text, ast
#-------------------------------------------------------------------------------
