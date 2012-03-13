#!/usr/bin/env python

try:
    import json
except:
    import simplejson as json
import sys
import cStringIO
import optparse
from plex import Scanner, Lexicon, Str, State, IGNORE, Begin, Any, AnyChar, Range, Rep

native_types = [ "int", "float", "string", "bool" ]
letter = Range("AZaz")
digit = Range("09")
under = Str("_")
ident = letter + Rep(letter | digit | under)
arr_ident = Str("[]") + ident
space = Any(" \t\n\r")
comment = Str("// ") | Str("//")

class IdlParseException(Exception):

    def __init__(self, errors):
        Exception.__init__(self)
        self.errors = errors

    def __str__(self):
        s = ""
        for e in self.errors:
            if s != "":
                s += ", "
            s += "line: %d message: %s" % (e["line"], e["message"])
        return s

class IdlScanner(Scanner):

    def eof(self):
        if self.cur:
            self.add_error("Unexpected end of file")

    def add_error(self, message, line=-1):
        if line < 0:
            (name, line, col) = self.position()
        self.errors.append({"line": line, "message": message})

    def begin_struct(self, text):
        self.check_dupe_name(text)
        self.cur = { "name" : text, "type" : "struct", "extends" : "",
                     "comment" : self.get_comment(), "fields" : [] }
        self.begin('start-block')

    def begin_enum(self, text):
        self.check_dupe_name(text)
        self.cur = { "name" : text, "type" : "enum", 
                     "comment" : self.get_comment(), "values" : [] }
        self.begin('start-block')

    def begin_interface(self, text):
        self.check_dupe_name(text)
        self.cur = { "name" : text, "type" : "interface", 
                     "comment" : self.get_comment(), "functions" : [] }
        self.begin('start-block')

    def check_dupe_name(self, name):
        if self.types.has_key(name):
            self.add_error("type %s already defined" % name)

    def start_block(self, text):
        t = self.cur["type"]
        if t == "struct":
            self.begin("fields")
        elif t == "enum":
            self.begin("values")
        elif t == "interface":
            self.begin("functions")
        else:
            raise Exception("Invalid type: %s" % t)

    def end_block(self, text):
        self.parsed.append(self.cur)
        self.types[self.cur["name"]] = self.cur
        self.cur = None
        self.begin('')

    def begin_field(self, text):
        self.field = { "name" : text }
        self.begin("field")

    def end_field(self, text):
        self.field["type"] = text
        self.cur["fields"].append(self.field)
        self.field = None
        self.begin("fields")

    def begin_function(self, text):
        self.function = { "name" : text, "comment" : self.get_comment(), "params" : [ ] }
        self.begin("function-start")

    def begin_param(self, text):
        self.param = { "name" : text }
        self.begin("param")

    def end_param(self, text):
        self.param["type"] = text
        self.function["params"].append(self.param)
        self.param = None
        self.begin("end-param")

    def end_return(self, text):
        self.function["returns"] = text
        self.cur["functions"].append(self.function)
        self.function = None
        self.begin("end-function")

    def end_value(self, text):
        if not text in self.cur["values"]:
            val = { "value" : text, "comment" : self.get_comment() }
            self.last_comment = ""
            self.cur["values"].append(val)

    def get_comment(self):
        comment = ""
        if self.comment and len(self.comment) > 0:
            comment = "".join(self.comment)
        self.comment = None
        return comment

    def start_comment(self, text):
        if self.comment:
            self.comment.append("\n")
        else:
            self.comment = []
        self.prev_state = self.state_name
        self.begin("comment")

    def append_comment(self, text):
        self.comment.append(text)

    def end_comment(self, text):
        self.begin(self.prev_state)
        self.prev_state = None

    def end_extends(self, text):
        if self.cur and self.cur["type"] == "struct":
            self.cur["extends"] = text
        else:
            self.add_error("extends is only supported for struct types")

    lex = Lexicon([
            (space,      IGNORE),
            (Str('struct '),   Begin('struct-start')),
            (Str('enum '),   Begin('enum-start')),
            (Str('interface '),   Begin('interface-start')),
            (comment,    start_comment),
            State('struct-start', [
                    (ident,    begin_struct),
                    (space,    IGNORE),
                    (AnyChar, "Missing identifier") ]),
            State('enum-start', [
                    (ident,    begin_enum),
                    (space,    IGNORE),
                    (AnyChar, "Missing identifier") ]),
            State('interface-start', [
                    (ident,    begin_interface),
                    (space,    IGNORE),
                    (AnyChar, "Missing identifier") ]),
            State('start-block', [
                    (space, IGNORE),
                    (Str("extends"), Begin('extends')),
                    (Str('{'), start_block) ]),
            State('extends', [
                    (space, IGNORE),
                    (ident, end_extends),
                    (Str('{'), start_block) ]),
            State('fields', [
                    (ident,    begin_field),
                    (space,    IGNORE),
                    (Str('{'), 'invalid'),
                    (Str('}'), end_block) ]),
            State('field', [
                    (ident,    end_field),
                    (arr_ident, end_field),
                    (Str("\n"), 'invalid'),
                    (space,    IGNORE),
                    (Str('{'), 'invalid'),
                    (Str('}'), 'invalid') ]),
            State('functions', [
                    (ident,    begin_function),
                    (space,    IGNORE),
                    (comment,  start_comment),
                    (Str('{'), 'invalid'),
                    (Str('}'), end_block) ]),
            State('function-start', [
                    (Str("("), Begin('params')),
                    (Str("\n"), 'invalid'),
                    (space,    IGNORE) ]),
            State('params', [
                    (ident,    begin_param),
                    (space,    IGNORE),
                    (Str(")"), Begin('function-return')) ]),
            State('end-param', [
                    (space, IGNORE),
                    (Str(","), Begin('params')),
                    (Str(")"), Begin('function-return')) ]),
            State('param', [
                    (ident,    end_param),
                    (arr_ident, end_param),
                    (space,    IGNORE) ]),
            State('function-return', [
                    (space,    IGNORE),
                    (ident,    end_return),
                    (arr_ident, end_return) ]),
            State('end-function', [
                    (Str("\n"), Begin('functions')),
                    (space, IGNORE) ]),
            State('values', [
                    (ident,    end_value),
                    (space,    IGNORE),
                    (comment,  start_comment),
                    (Str('{'), 'invalid'),
                    (Str('}'), end_block) ]),
            State('comment', [
                    (Str("\n"),     end_comment),
                    (AnyChar, append_comment) ])
            ])

    def __init__(self, f, name):
        Scanner.__init__(self, self.lex, f, name)
        self.parsed = [ ]
        self.errors = [ ]
        self.types = { }
        self.comment = None
        self.cur = None

    def parse(self):
        while True:
            (t, name) = self.read()
            if t is None:
                break
            else:
                self.add_error(t)
                break

    def check_cycle(self, cur_type, types):
        if cur_type.find("[]") == 0:
            cur_type = cur_type[2:]

        if cur_type in native_types:
            pass
        elif not self.types.has_key(cur_type):
            self.add_error("undefined type: %s" % cur_type, line=0)
        else:
            cur = self.types[cur_type]
            if cur_type in types:
                self.add_error("cycle detected in: %s %s" % (cur["type"], cur["name"]), 
                               line=0)
            else:
                types.append(cur_type)
                if cur["type"] == "struct":
                    for f in cur["fields"]:
                        self.check_cycle(f["type"], types)
                elif cur["type"] == "interface":
                    # interface types must be top-level, so if len(types) > 1, we
                    # know this interface was used as a type in a function or struct
                    if len(types) > 1:
                        self.add_error("interface %s cannot be a field type" % cur["name"], line=0)
                    for f in cur["functions"]:
                        for p in f["params"]:
                            self.check_cycle(p["type"], types)
                        self.check_cycle(f["returns"], types)

    def validate(self):
        for t in self.parsed:
            self.check_cycle(t["name"], [])

def parse_str(idl, name="", validate=True):
    reader = cStringIO.StringIO(idl)
    return parse(reader, name, validate=validate)

def parse(reader, name, validate=True):
    scanner = IdlScanner(reader, name)
    scanner.parse()
    if validate:
        scanner.validate()
    if len(scanner.errors) == 0:
        return scanner.parsed
    else:
        raise IdlParseException(scanner.errors)
    
if __name__ == "__main__":
    parser = optparse.OptionParser("usage: %prog [options] [idl filename]")
    parser.add_option("-i", "--stdin", dest="stdin", action="store_true",
                      default=False, help="Read IDL from STDIN")
    (options, args) = parser.parse_args()
    if options.stdin:
        print json.dumps(parse_str(sys.stdin.read()))
    elif len(args) < 1:
        parser.error("Incorrect number of args")
    else:
        f = open(args[0])
        print json.dumps(parse(f, args[0]))
        f.close()
