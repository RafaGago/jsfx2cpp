import ply.yacc as yacc
from copy import deepcopy
from lexer import tokens, CompileError

#Parser as in eel2, almost vanilla, with no modifications

class Node:
    def __init__(self, *args, **kwargs):
        self.reset(*args, **kwargs)

    def reset(
        self,
        ntype,
        lhs,
        rhs = [],
        line = -1,
        arithmetic=False,
        logic=False,
        comparison=False,
        integer=False,
        parentheses=False,
        bottom=False,
        assignable=True
        ):
        # TODO: just storing lineno of the fist token, could store the range
        self.line = line
        self.type = ntype
        self.lhs = []
        self.set_lhs(lhs)
        self.rhs = []
        self.set_rhs(rhs)
        self.is_arithmetic = arithmetic
        self.is_logic = logic
        self.is_comparison = comparison
        self.is_integer = integer
        self.has_parentheses = parentheses
        self.is_bottom = bottom #bottom elements have no array on lhs and rhs
        self.is_assignable = assignable

    def __str__ (self):
        return '\n'.join (self.debug_iterate([]))

    def __repr__ (self):
        return str(self)

    def debug_iterate (self, out = [], depth = 0):
        indent = ' ' * depth * 2
        indent1 = ' ' * ((depth * 2) + 2)

        out.append (f"{indent}'{self.type}'")
        out.append (f"{indent}LHS")
        for v in self.lhs or []:
            if type (v) is Node:
                v.debug_iterate (out, depth + 1)
            else:
                out.append (f"{indent1}{str (v)}")

        if self.rhs is None or len (self.rhs) == 0:
            return out

        out.append (f"{indent}RHS")
        for v in self.rhs:
            if type (v) is Node:
                v.debug_iterate (out, depth + 1)
            else:
                out.append (f"{indent1}{str (v)}")
        return out

    def set_children (self, children, on_lhs):
        for n in children:
            if type(n) is Node:
                n.parent = self
        if on_lhs:
            self.lhs = children
        else:
            self.rhs = children

    def set_lhs (self, lhs):
        self.set_children (lhs, on_lhs=True)

    def set_rhs (self, rhs):
        self.set_children (rhs, on_lhs=False)

    def copy (self, new_parent=None):
        cp = deepcopy (self)
        cp.update_parents (new_parent)
        return cp

    def update_children_parents (self, on_lhs):
        # Full rebuild of the parent backreferences, necessary after
        # invalidating iterators (e.g. deepcopy)
        dst = self.lhs if on_lhs else self.rhs
        for n in dst:
            if type(n) is Node:
                n.update_parents (self)

    def update_parents (self, parent=None):
        self.parent = parent
        self.update_children_parents (on_lhs=True)
        self.update_children_parents (on_lhs=False)

# this was done with:
# https://github.com/dabeaz/ply/tree/master/example/yply
#
# Then:
# -Replace '''' by ' '''
# -Added "value" and replaced value
# -replace the tokens, take them from the lexer
# -replaced p_more_params_2 to be a parameter pack
# -replaced string to string_literal
# -replaced identifiers to have namespace detection

start = 'program'

precedence =  []

def p_value(p):
    '''value : NUM
             | NUM_UNDER_ONE
             | HEX
             | MASK
             | E
             | PI
             | PHI
             | CHAR
    '''
    p[0] = Node ("value", [str(p[1])], bottom=True, line=p.lineno (1))

# -------------- RULES ----------------
def p_more_params_1(p):
    '''more_params : expression'''
    p[0] = p[1]

def p_more_params_2(p):
    '''more_params : expression ',' more_params'''
    if type(p[1]) is Node and p[1].type == 'parameter_pack':
        p[1].lhs.append(p[3]);
        p[0] = p[1]
    else:
        p[0] = Node ("parameter_pack", [p[1], p[3]], line=p.lineno (1))

def p_string_1(p):
    '''string_literal : STRING_LITERAL'''
    p[0] = Node ("string_literal", p[1], bottom = True, line=p.lineno (1))

def p_string_2(p):
    '''string_literal : STRING_LITERAL string_literal'''
    lit  = p[1][:-1] # getting rid of trailing quote
    lit += p[2].lhs[0][1:] # getting rid of leading quote
    p[0] = Node ("string_literal", lit, bottom = True, line=p.lineno (1))

def p_identifier(p):
    '''identifier : IDENTIFIER'''
    v = p[1].replace('..', '.!parent.')
    v = v.split(".") # namespace splitting
    name = [ x.replace('!parent', '..').lower() for x in v]
    p[0] = Node ("identifier", name, [], bottom = True, line=p.lineno (1))

def p_assignable_value_1(p):
    '''assignable_value : identifier'''
    p[0] = p[1]

def p_assignable_value_2(p):
    '''assignable_value : '(' expression ')' '''
    p[2].has_parentheses = True
    p[0] = p[2]

def p_assignable_value_3(p):
    '''assignable_value : identifier '(' expression ')' '(' expression ')' '''
    p[0] = Node ("call-x2", [p[1]], [p[3], p[6]], line=p.lineno (1))

def p_assignable_value_3_a(p):
    '''assignable_value : WHILE '(' expression ')' '(' expression ')' '''
    p[0] = Node ("loop", [p[3]], [p[6]], line=p.lineno (1))

def p_assignable_value_4(p):
    '''assignable_value : identifier '(' expression ')' '''
    p[0] = Node ("call", [p[1]], [p[3]], line=p.lineno (1))

def p_assignable_value_4_a(p):
    '''assignable_value : WHILE '(' expression ')' '''
    p[0] = Node ("loop-eval-result", [], [p[3]], line=p.lineno (1))

def p_assignable_value_5(p):
    '''assignable_value : identifier '(' ')' '''
    p[0] = Node ("call", [p[1]], line=p.lineno (1))

def p_assignable_value_6(p):
    '''assignable_value : identifier '(' expression ',' expression ')' '''
    p[0] = Node ("call", [p[1]], [p[3], p[5]], line=p.lineno (1))

def p_assignable_value_6_a(p):
    '''assignable_value : LOOP '(' expression ',' expression ')' '''
    p[0] = Node ("loop-counter", [p[3]], [p[5]], line=p.lineno (1))

def p_assignable_value_7(p):
    '''assignable_value : identifier '(' expression ',' expression ',' more_params ')' '''

    def clear_pp (src, dst=[]):
        for n in src:
            if type (n) is Node and n.type == 'parameter_pack':
                clear_pp (n.lhs, dst)
            else:
                dst.append (n)
        return dst

    p[0] = Node(
        "call", [p[1]], clear_pp ([p[3], p[5], p[7]]), line=p.lineno (1)
        )

def p_assignable_value_8(p):
    '''assignable_value : rvalue '[' ']' '''
    n = Node ("value", ['0'], bottom=True, line=p.lineno (1))
    p[0] = Node ("[]", [p[1]], [n], line=p.lineno (1))

def p_assignable_value_9(p):
    '''assignable_value : rvalue '[' expression ']' '''
    #8MB space
    #1MB gmem
    p[0] = Node ("[]", [p[1]], [p[3]], line=p.lineno (1))

def p_rvalue_1(p):
    '''rvalue : value'''
    p[0] = p[1]

def p_rvalue_2(p):
    '''rvalue : STRING_IDENTIFIER'''
    p[0] = p[1]

def p_rvalue_3(p):
    '''rvalue : string_literal'''
    p[0] = p[1]

def p_rvalue_4(p):
    '''rvalue : assignable_value'''
    p[0] = p[1]

def p_assignment_1(p):
    '''assignment : rvalue'''
    p[0] = p[1]

def p_assignment_2(p):
    '''assignment : assignable_value '=' if_else_expr'''
    p[0] = Node ("=",  [p[1]], [p[3]], line=p.lineno (1))

def expand_assignment_with_op (lhs, op, rhs, line, **kwargs):
    node = Node (op,  [deepcopy(lhs)], [rhs], line=line, **kwargs)
    return Node ("=",  [lhs], [node], line=line)

def p_assignment_3(p):
    '''assignment : assignable_value TOKEN_ADD_OP if_else_expr'''
    p[0] = expand_assignment_with_op (
        p[1], '+', p[3], p.lineno (1), arithmetic=True
        )

def p_assignment_4(p):
    '''assignment : assignable_value TOKEN_SUB_OP if_else_expr'''
    p[0] = expand_assignment_with_op (
        p[1], '-', p[3], p.lineno (1), arithmetic=True
        )

def p_assignment_5(p):
    '''assignment : assignable_value TOKEN_MOD_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '%', p[3], p.lineno (1), arithmetic=True
        )

def p_assignment_6(p):
    '''assignment : assignable_value TOKEN_OR_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '|', p[3], p.lineno (1), arithmetic=True, integer=True
        )

def p_assignment_7(p):
    '''assignment : assignable_value TOKEN_AND_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '&', p[3], p.lineno (1), arithmetic=True, integer=True
        )

def p_assignment_8(p):
    '''assignment : assignable_value TOKEN_XOR_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '~', p[3], p.lineno (1), arithmetic=True, integer=True
        )

def p_assignment_9(p):
    '''assignment : assignable_value TOKEN_DIV_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '/', p[3], p.lineno (1), arithmetic=True
        )

def p_assignment_10(p):
    '''assignment : assignable_value TOKEN_MUL_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '*', p[3], p.lineno (1), arithmetic=True
        )

def p_assignment_11(p):
    '''assignment : assignable_value TOKEN_POW_OP if_else_expr'''
    p[0] = expand_assignment_with_op(
        p[1], '^', p[3], p.lineno (1), arithmetic=True
        )

def p_assignment_12(p):
    '''assignment : STRING_IDENTIFIER '=' if_else_expr'''
    p[0] = Node ("strcpy",  [p[1]], [p[3]], line=p.lineno (1))

def p_assignment_13(p):
    '''assignment : STRING_IDENTIFIER TOKEN_ADD_OP if_else_expr'''
    p[0] = Node ("strcat",  [p[1]], [p[3]], line=p.lineno (1))

def p_unary_expr_1(p):
    '''unary_expr : assignment'''
    p[0] = p[1]

def p_unary_expr_2(p):
    '''unary_expr : '+' unary_expr'''
    p[0] = p[2]

def p_unary_expr_3(p):
    '''unary_expr : '-' unary_expr'''
    p[0] = Node ("MINUS",  [p[2]], line=p.lineno (1))

def p_unary_expr_4(p):
    '''unary_expr : '!' unary_expr'''
    p[0] = Node ('!',  [p[2]], line=p.lineno (1))

def p_pow_expr_1(p):
    '''pow_expr : unary_expr'''
    p[0] = p[1]

def p_pow_expr_2(p):
    '''pow_expr : pow_expr '^' unary_expr'''
    p[0] = Node  ("^", [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_mod_expr_1(p):
    '''mod_expr : pow_expr'''
    p[0] = p[1]

def p_mod_expr_2(p):
    '''mod_expr : mod_expr '%' pow_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_mod_expr_3(p):
    '''mod_expr : mod_expr TOKEN_SHL pow_expr'''
    p[0] = Node  ("<<", [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_mod_expr_4(p):
    '''mod_expr : mod_expr TOKEN_SHR pow_expr'''
    p[0] = Node  (">>", [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_div_expr_1(p):
    '''div_expr : mod_expr'''
    p[0] = p[1]

def p_div_expr_2(p):
    '''div_expr : div_expr '/' mod_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_mul_expr_1(p):
    '''mul_expr : div_expr'''
    p[0] = p[1]

def p_mul_expr_2(p):
    '''mul_expr : mul_expr '*' div_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_sub_expr_1(p):
    '''sub_expr : mul_expr'''
    p[0] = p[1]

def p_sub_expr_2(p):
    '''sub_expr : sub_expr '-' mul_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_add_expr_1(p):
    '''add_expr : sub_expr'''
    p[0] = p[1]

def p_add_expr_2(p):
    '''add_expr : add_expr '+' sub_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], arithmetic=True, line=p.lineno (1))

def p_andor_expr_1(p):
    '''andor_expr : add_expr'''
    p[0] = p[1]

def p_andor_expr_2(p):
    '''andor_expr : andor_expr '&' add_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], logic=True, line=p.lineno (1))

def p_andor_expr_3(p):
    '''andor_expr : andor_expr '|' add_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], logic=True, line=p.lineno (1))

def p_andor_expr_4(p):
    '''andor_expr : andor_expr '~' add_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], logic=True, line=p.lineno (1))

def p_cmp_expr_1(p):
    '''cmp_expr : andor_expr'''
    p[0] = p[1]

def p_cmp_expr_2(p):
    '''cmp_expr : cmp_expr '<' andor_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_3(p):
    '''cmp_expr : cmp_expr '>' andor_expr'''
    p[0] = Node (p[2],  [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_4(p):
    '''cmp_expr : cmp_expr TOKEN_LTE andor_expr'''
    p[0] = Node  ("<=", [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_5(p):
    '''cmp_expr : cmp_expr TOKEN_GTE andor_expr'''
    p[0] = Node  (">=", [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_6(p):
    '''cmp_expr : cmp_expr TOKEN_EQ andor_expr'''
    p[0] = Node  ("==_", [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_7(p):
    '''cmp_expr : cmp_expr TOKEN_EQ_EXACT andor_expr'''
    # direct in place translation to C equivalent
    p[0] = Node  ("==", [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_8(p):
    '''cmp_expr : cmp_expr TOKEN_NE andor_expr'''
    p[0] = Node  ("!=_", [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_cmp_expr_9(p):
    '''cmp_expr : cmp_expr TOKEN_NE_EXACT andor_expr'''
    # direct in place translation to C equivalent
    p[0] = Node  ("!=", [p[1]] , [p[3]], comparison=True, line=p.lineno (1))

def p_logical_and_or_expr_1(p):
    '''logical_and_or_expr : cmp_expr'''
    p[0] = p[1]

def p_logical_and_or_expr_2(p):
    '''logical_and_or_expr : logical_and_or_expr TOKEN_LOGICAL_AND cmp_expr'''
    p[0] = Node  ("&&", [p[1]] , [p[3]], logic=True, line=p.lineno (1))

def p_logical_and_or_expr_3(p):
    '''logical_and_or_expr : logical_and_or_expr TOKEN_LOGICAL_OR cmp_expr'''
    p[0] = Node  ("||", [p[1]] , [p[3]], logic=True, line=p.lineno (1))

def p_if_else_expr_1(p):
    '''if_else_expr : logical_and_or_expr'''
    p[0] = p[1]

def p_if_else_expr_2(p):
    '''if_else_expr : logical_and_or_expr '?' if_else_expr ':' if_else_expr'''
    p[0] = Node  ("if", [p[1]], [p[3], p[5]], line=p.lineno (1))

def p_if_else_expr_3(p):
    '''if_else_expr : logical_and_or_expr '?' ':' if_else_expr'''
    neg = Node ('!',  [p[1]], parentheses=True, line=p.lineno (1))
    p[0] = Node  ("if", [neg], [p[4]], line=p.lineno (1))

def p_if_else_expr_4(p):
    '''if_else_expr : logical_and_or_expr '?' if_else_expr'''
    p[0] = Node  ("if", [p[1]], [p[3]], line=p.lineno (1))

def p_expression_1(p):
    '''expression : if_else_expr'''
    p[0] = p[1]

def p_expression_2(p):
    '''expression : expression ';' if_else_expr'''
    # compound statement, make a seq
    if type(p[1]) is Node and p[1].type == 'seq':
        p[1].lhs.append(p[3]);
        p[0] = p[1]
    else:
        p[0] = Node ("seq", [p[1], p[3]], line=p.lineno (1))

def p_expression_3(p):
    '''expression : expression ';' '''
    p[0] = p[1]

# Program needs to include functions

#def p_program_1(p):
#    '''program : expression'''
#    if type(p[1]) is Node and p[1].type == 'seq':
#        p[0] = p[1]
#    else:
#        # make any program a compound statement at the top for simplicity.
#        p[0] = Node ("seq", [p[1]])

# ADDONS: Function + p_error

def p_id_list_1(p):
    '''id_list :'''
    p[0] = Node ("id_list",  [], bottom=True)

def p_id_list_2(p):
    '''id_list : identifier'''
    p[0] = Node ("id_list",  [p[1].lhs], line=p.lineno (1), bottom=True)

def p_id_list_3(p):
    '''id_list : id_list ',' identifier'''
    if type(p[1]) is Node and p[1].type == 'id_list':
        p[1].lhs.append(p[3].lhs);
        p[0] = p[1]
    else:
        p[0] = Node(
            "id_list",
             [p[1].lhs, p[3].lhs],
             line=p.lineno (1),
             bottom=True)

def p_function_modifier(p):
    '''function_modifier : LOCAL '(' id_list ')'
                         | STATIC '(' id_list ')'
                         | INSTANCE '(' id_list ')'
                         | GLOBALS '(' id_list ')'
                         | GLOBAL '(' id_list ')'
    '''
    modif = p[1] if 'globals' not in p[1] else 'global'
    assert(p[3].type == "id_list")
    p[0] = Node (modif, p[3].lhs, line=p.lineno (1), bottom=True)

def p_function_modifiers_1(p):
    '''function_modifiers : '''
    p[0] = Node ("modifiers", [])

def p_function_modifiers_2(p):
    '''function_modifiers : function_modifier'''
    p[0] = Node ("modifiers", [p[1]], line=p.lineno (1))

def p_function_modifiers_3(p):
    '''function_modifiers : function_modifiers function_modifier'''
    if type(p[1]) is Node and p[1].type == 'modifiers':
        p[1].lhs.append(p[2]);
        p[0] = p[1]
    else:
        p[0] = Node ("modifiers", [p[1], p[2]], line=p.lineno (1))

def p_function_1(p):
    '''function : FUNCTION identifier '(' id_list ')' function_modifiers '(' expression ')' ';' '''
    content = p[8]
    if type (p[8]) is Node and p[8].type != 'seq':
        content = Node ("seq", [p[8]], line=p.lineno (8))

    p[0] = Node ("function",  [p[2], p[4], p[6]], [content], line=p.lineno (1))

def p_section(p):
    '''section : SECTION '''
    p[0] = Node ("section", p[1], bottom=True, line=p.lineno (1))

def p_global_expression_1(p):
    '''global_expression : function
                         | section
                         | expression
    '''
    p[0] = p[1]

def p_global_expression_2(p):
    '''global_expression : global_expression function
                         | global_expression section
                         | global_expression expression
    '''
    if type (p[1]) is Node and p[1].type == 'seq':
        p[1].lhs.append (p[2])
        p[0] = p[1]
    else:
        p[0] = Node ("seq", [p[1], p[2]], line=p.lineno (1))

def p_program_1(p):
    '''program : global_expression'''
    p[0] = p[1]

def p_error(p):
    raise CompileError(
        f"Invalid expression: '{p.value[0]}'", p.lexpos, p.lineno)

# End of ADDONS
# -------------- RULES END ----------------
if __name__ == '__main__':
    from ply import *
    yacc.yacc()
else:
    parser = yacc.yacc()
