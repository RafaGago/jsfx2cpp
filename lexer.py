import ply.lex as lex

class CompileError(Exception):
    def __init__(self, message, char_idx, line):
        super(CompileError, self).__init__(message)
        self.idx = char_idx
        self.line = line

# Moved hex to the beggining (more prio), as it clashes with NUM.
# 0[xX][0-9a-fA-F]*             PARSENUM;
# \$[xX][0-9a-fA-F]*            PARSENUM;
def t_HEX(t):
     r'[\$0][xX][0-9a-fA-F]*'
     t.value = t.value.replace('$', '0')
     t.value = f'((double) {t.value})'
     return t

# \.[0-9]+                      PARSENUM;
t_NUM_UNDER_ONE = r'\.[0-9]*'

# [0-9]+\.?[0-9]*               PARSENUM;
def t_NUM(t):
    r'[0-9]+\.?[0-9]*'
    if '.' not in t.value:
        t.value += '.'
    return t

# \$\~[0-9]*                    PARSENUM;
def t_MASK(t):
    r'\$\~[0-9]*'
    t.value = t.value[2:]
    t.value = f'(((uint64_t) 1) << ({t.value} > 53) ? 53 : {t.value})'
    # Maybe cast to double here?
    return t

# \$[Ee]                        PARSENUM;
def t_E(t):
    r'\$[Ee]'
    t.value = '2.71828183'
    return t

# \$[Pp][Ii]                    PARSENUM;
def t_PI(t):
    r'\$[Pp][Ii]'
    t.value = '3.141592653589793'
    return t

# \$[Pp][Hh][Ii]                PARSENUM;
def t_PHI(t):
    r'\$[Pp][Hh][Ii]'
    t.value = '1.61803399'
    return t

# \$\'.\'                       PARSENUM;
t_CHAR = r"\$'.'"

# The parser has to build VALUE as a sum of this.
# num = NUM | NUM_UNDERZERO | HEX | MASK | E | PI | PHI | CHAR

# \#[a-zA-Z0-9\._]*             *yylval = nseel_translate(yyextra,yytext, 0); return STRING_IDENTIFIER;
t_STRING_IDENTIFIER = r'\#[a-zA-Z0-9\._]*' # Notice that they can contain dots.

# \<\<                          return TOKEN_SHL;
t_TOKEN_SHL = r'\<\<'
# \>\>                          return TOKEN_SHR;
t_TOKEN_SHR = r'\>\>'
# \<=                          return TOKEN_LTE;
t_TOKEN_LTE = r'\<='
# \>=                          return TOKEN_GTE;
t_TOKEN_GTE = r'\>='
# ==                              return TOKEN_EQ;
t_TOKEN_EQ = r'=='
# ===                              return TOKEN_EQ_EXACT;
t_TOKEN_EQ_EXACT = r'==='
# \!=                              return TOKEN_NE;
t_TOKEN_NE = r'\!='
# \!==                              return TOKEN_NE_EXACT;
t_TOKEN_NE_EXACT = r'\!=='
# \&\&                              return TOKEN_LOGICAL_AND;
t_TOKEN_LOGICAL_AND = r'\&\&'
# \|\|                              return TOKEN_LOGICAL_OR;
t_TOKEN_LOGICAL_OR = r'\|\|'
# \+=                             return TOKEN_ADD_OP;
t_TOKEN_ADD_OP = r'\+='
# -=                              return TOKEN_SUB_OP;
t_TOKEN_SUB_OP = r'-='
# %=                              return TOKEN_MOD_OP;
t_TOKEN_MOD_OP = r'%='
# \|=                             return TOKEN_OR_OP;
t_TOKEN_OR_OP = r'\|='
# \&=                             return TOKEN_AND_OP;
t_TOKEN_AND_OP = r'\&='
# \~=                             return TOKEN_XOR_OP;
t_TOKEN_XOR_OP = r'\~='
# \/=                             return TOKEN_DIV_OP;
t_TOKEN_DIV_OP = r'\/='
# \*=                             return TOKEN_MUL_OP;
t_TOKEN_MUL_OP = r'\*='
# \^=                             return TOKEN_POW_OP;
t_TOKEN_POW_OP = r'\^='

reserved = {
    'function' : 'FUNCTION',
    'local'    : 'LOCAL',
    'static'   : 'STATIC',
    'instance' : 'INSTANCE',
    'globals'  : 'GLOBALS',
    'global'   : 'GLOBAL',
    'loop'     : 'LOOP',
    'while'    : 'WHILE',
}

# [a-zA-Z_][a-zA-Z0-9\._]*        &yylval = nseel_createCompiledValuePtr((compileContext *)yyextra, NULL, yytext); return IDENTIFIER;
def t_IDENTIFIER(t):
    r'[a-zA-Z_][a-zA-Z0-9\._]*'
    t.type = reserved.get (t.value, 'IDENTIFIER') # Check for reserved words
    return t

# [ \t\r\n]+      /* whitespace */
t_ignore  = ' \t\r\n'

# \/\/.*$         /* comment */
def t_ONELINE_COMMENT(p):
    r'\/\/[^\n\r]+?(?:\*\)|[\n\r])'
    pass

# "/*"            { comment(yyscanner); }
#
# .       return (int)yytext[0];
#

def t_MULTILINE_COMMENT(p):
    r'(?s)/\*.*?\*/'
    pass

# missing on the definition

t_STRING_LITERAL = r'"[^"\\]*(\\.[^"\\]*)*"'

literals = "+-*=/:,();?<>%\"[]{}&|!^"

def t_SECTION(t):
     r'@[a-z]*'
     t.value = t.value[1:]
     return t

def t_newline(t):
    r'\n+'
    t.lexer.lineno += len(t.value)

 # Error handling rule
def t_error(t):
    raise CompileError(
        f"Illegal character: '{t.value[0]}'", t.lexpos, t.lineno)

tokens = [
    'NUM_UNDER_ONE',
    'NUM',
    'HEX',
    'MASK',
    'E',
    'PI',
    'PHI',
    'CHAR',
    'STRING_IDENTIFIER',
    'TOKEN_SHL',
    'TOKEN_SHR',
    'TOKEN_LTE',
    'TOKEN_GTE',
    'TOKEN_EQ',
    'TOKEN_EQ_EXACT',
    'TOKEN_NE',
    'TOKEN_NE_EXACT',
    'TOKEN_LOGICAL_AND',
    'TOKEN_LOGICAL_OR',
    'TOKEN_ADD_OP',
    'TOKEN_SUB_OP',
    'TOKEN_MOD_OP',
    'TOKEN_OR_OP',
    'TOKEN_AND_OP',
    'TOKEN_XOR_OP',
    'TOKEN_DIV_OP',
    'TOKEN_MUL_OP',
    'TOKEN_POW_OP',
    'IDENTIFIER',
    'STRING_LITERAL',
    'SECTION'
] + list (reserved.values())

# Build the lexer
lexer = lex.lex()
