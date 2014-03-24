from __future__ import with_statement
import os, subprocess, re, sys, glob
from memoize import memoize

__all__ = ["include_imports"]

file_mtimes = {}
file_contents = {}
lib_imports_fast = {}
lib_imports_slow = {}

DEFAULT_VERBOSE=1

IMPORT_REG = re.compile('^R[0-9]+:[0-9]+ ([^ ]+) <> <> lib$', re.MULTILINE)
IMPORT_LINE_REG = re.compile(r'^\s*(?:Require\s+Import|Require\s+Export|Require|Load\s+Verbose|Load)\s+(.*?)\.(?:\s|$)', re.MULTILINE | re.DOTALL)

def DEFAULT_LOG(text):
    print(text)

@memoize
def filename_of_lib(lib, topname='__TOP__', ext='.v'):
    if lib[:len(topname + '.')] == topname + '.':
        lib = lib[len(topname + '.'):]
        lib = lib.replace('.', os.sep)
        return os.path.relpath(os.path.normpath(lib + ext), '.')
    else:
        # is this the right thing to do?
        lib = lib.replace('.', os.sep)
        for dirpath, dirname, filenames in os.walk('.', followlinks=True):
            filename = os.path.relpath(os.path.normpath(os.path.join(dirpath, lib + ext)), '.')
            if os.path.exists(filename):
                return filename
        return os.path.relpath(os.path.normpath(lib + ext), '.')

    return filename_of_lib_helper(lib, topname) + ext

def lib_of_filename(filename, topname='__TOP__', exts=('.v', '.glob')):
    filename = os.path.relpath(filename, '.')
    for ext in exts:
        if filename[-len(ext):] == ext:
            filename = filename[:-len(ext)]
            break
    if '.' in filename:
        print("WARNING: There is a dot (.) in filename %s; the library conversion probably won't work." % filename)
    return topname + '.' + filename.replace(os.sep, '.')

def get_file(filename, verbose=DEFAULT_VERBOSE, log=DEFAULT_LOG):
    if filename[-2:] != '.v': filename += '.v'
    if filename not in file_contents.keys() or file_mtimes[filename] < os.stat(filename).st_mtime:
        if verbose: log('getting %s' % filename)
        try:
            with open(filename, 'r', encoding='UTF-8') as f:
                file_contents[filename] = f.read()
        except TypeError:
            with open(filename, 'r') as f:
                file_contents[filename] = f.read()
        file_mtimes[filename] = os.stat(filename).st_mtime
    return file_contents[filename]

def get_all_v_files(directory, exclude=tuple()):
    all_files = []
    exclude = [os.path.normpath(i) for i in exclude]
    for dirpath, dirnames, filenames in os.walk(directory):
        all_files += [os.path.relpath(name, '.') for name in glob.glob(os.path.join(dirpath, '*.v'))
                      if os.path.normpath(name) not in exclude]
    return all_files

@memoize
def get_makefile_contents(coqc, topname, v_files, verbose, log):
    cmds = ['coq_makefile', 'COQC', '=', coqc, '-R', '.', topname] + list(v_files)
    if verbose:
        log(' '.join(cmds))
    p_make_makefile = subprocess.Popen(cmds,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
    return p_make_makefile.communicate()

def make_globs(libnames, verbose=DEFAULT_VERBOSE, topname='__TOP__', log=DEFAULT_LOG, coqc='coqc'):
    extant_libnames = [i for i in libnames
                       if os.path.exists(filename_of_lib(i, topname=topname, ext='.v'))]
    if len(extant_libnames) == 0: return
    filenames_v = [filename_of_lib(i, topname=topname, ext='.v') for i in extant_libnames]
    filenames_glob = [filename_of_lib(i, topname=topname, ext='.glob') for i in extant_libnames]
    if all(os.path.exists(glob_name) for glob_name in filenames_glob):
        return
    extra_filenames_v = get_all_v_files('.', filenames_v)
    (stdout, stderr) = get_makefile_contents(coqc, topname, tuple(sorted(filenames_v + extra_filenames_v)), verbose, log)
    if verbose:
        log(' '.join(['make', '-k', '-f', '-'] + filenames_glob))
    p_make = subprocess.Popen(['make', '-k', '-f', '-'] + filenames_glob, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    (stdout_make, stderr_make) = p_make.communicate(stdout)

def get_imports(lib, verbose=DEFAULT_VERBOSE, fast=False, log=DEFAULT_LOG, topname='__TOP__', coqc='coqc'):
    lib = norm_libname(lib, topname=topname)
    glob_name = filename_of_lib(lib, topname=topname, ext='.glob')
    v_name = filename_of_lib(lib, topname=topname, ext='.v')
    if not fast:
        if lib not in lib_imports_slow.keys():
            if not os.path.exists(glob_name):
                make_globs([lib], verbose=verbose, topname=topname, log=log, coqc=coqc)
            if os.path.exists(glob_name): # making succeeded
                with open(glob_name, 'r') as f:
                    contents = f.read()
                lines = contents.split('\n')
                lib_imports_slow[lib] = tuple(sorted(set(norm_libname(name, topname=topname)
                                                         for name in IMPORT_REG.findall(contents))))
                return lib_imports_slow[lib]
    # making globs failed, or we want the fast way, fall back to regexp
    if lib not in lib_imports_fast.keys():
        contents = get_file(v_name, verbose=verbose, log=log)
        imports_string = re.sub('\\s+', ' ', ' '.join(IMPORT_LINE_REG.findall(contents))).strip()
        lib_imports_fast[lib] = tuple(sorted(set(norm_libname(i, topname=topname)
                                                 for i in imports_string.split(' ') if i != '')))
    return lib_imports_fast[lib]

def norm_libname(lib, topname='__TOP__'):
    filename = filename_of_lib(lib, topname=topname)
    # TODO: Cache this lookup, if it's a bottleneck?
    if os.path.exists(filename):
        return lib_of_filename(filename, topname=topname)
    else:
        return lib

def merge_imports(imports, topname='__TOP__'):
    rtn = []
    for import_list in imports:
        for i in import_list:
            if norm_libname(i, topname=topname) not in rtn:
                rtn.append(norm_libname(i, topname=topname))
    return rtn

def recursively_get_imports(lib, verbose=DEFAULT_VERBOSE, fast=False, log=DEFAULT_LOG, topname='__TOP__', coqc='coqc'):
    lib = norm_libname(lib, topname=topname)
    glob_name = filename_of_lib(lib, topname=topname, ext='.glob')
    v_name = filename_of_lib(lib, topname=topname, ext='.v')
    if os.path.exists(v_name):
        imports = get_imports(lib, verbose=verbose, fast=fast, topname=topname, coqc=coqc)
        if not fast: make_globs(imports, verbose=verbose, topname=topname, log=log, coqc=coqc)
        imports_list = [recursively_get_imports(i, verbose=verbose, fast=fast, log=log, topname=topname, coqc=coqc)
                        for i in imports]
        return merge_imports(imports_list + [[lib]], topname=topname)
    return [lib]

def contents_without_imports(lib, verbose=DEFAULT_VERBOSE, log=DEFAULT_LOG, topname='__TOP__'):
    v_file = filename_of_lib(lib, topname=topname, ext='.v')
    contents = get_file(v_file, verbose=verbose, log=log)
    if '(*' in ' '.join(IMPORT_LINE_REG.findall(contents)):
        print('Warning: There are comments in your Require/Import/Export lines in %s.' % filename)
    return IMPORT_LINE_REG.sub('', contents)

def escape_lib(lib):
    return lib.replace('.', '_DOT_')

def group_by_first_component(lib_libname_pairs):
    rtn = dict((lib.split('.')[0], []) for lib, libname in lib_libname_pairs)
    for lib, libname in lib_libname_pairs:
        split_lib = lib.split('.')
        rtn[split_lib[0]].append(('.'.join(split_lib[1:]), libname))
    return rtn

def nest_iter_up_to(iterator):
    so_far = []
    for i in iterator:
        so_far.append(i)
        yield tuple(so_far)


def construct_import_list(import_libs):
    '''Takes a list of library names, and returns a list of imports in an order that should have modules representing files at the end.'''
    lib_components_list = [(libname, tuple(reversed(list(nest_iter_up_to(libname.split('.')))[:-1])))
                           for libname in import_libs]
    ret = list(map(escape_lib, import_libs))
    lib_components = [(libname, i, max(map(len, lst)) - len(i))
                      for libname, lst in lib_components_list
                      for i in lst]
    for libname, components, components_left in reversed(sorted(lib_components, key=(lambda x: x[2]))):
        ret.append(escape_lib(libname) + '.' + '.'.join(components))
    return ' '.join(ret)


def contents_as_module_without_require(lib, other_imports, module_include='Include', verbose=DEFAULT_VERBOSE, log=DEFAULT_LOG, topname='__TOP__'):
    v_name = filename_of_lib(lib, topname=topname, ext='.v')
    contents = get_file(v_name, verbose=verbose, log=log)
#    # normalize all the imports, and remove the requires
#    reg1 = re.compile(r'^(\s*Require\s+)((?:Import|Export)\s+)((?:[^\.]|\.(?!\s|$))+)(\.(?:\s|$))', flags=re.MULTILINE)
#    for req, imp_exp, modules, end in reg1.findall(contents):
#        new_modules = ' '.join(normalize_libname(name, topname=topname)
#                               for name in modules.split(' ')
#                               if name.strip() != '')
#        contents = contents.replace(req + imp_exp + modules + end, imp_exp + new_modules + end)
    reg1 = re.compile(r'^\s*Require\s+((?:Import|Export)\s)', flags=re.MULTILINE)
    contents = reg1.sub(r'\1', contents)
    reg2 = re.compile(r'^\s*Require\s+((?!Import\s+|Export\s+)(?:[^\.]|\.(?!\s|$))+\.(?:\s|$))', flags=re.MULTILINE)
    contents = reg2.sub(r'', contents)
    if verbose > 1: log(contents)
    module_name = escape_lib(lib)
    # import the top-level wrappers
    if len(other_imports) > 0:
        # we need to import the contents in the correct order.  Namely, if we have a module whose name is also the name of a directory (in the same folder), we want to import the file first.
        contents = 'Import %s.\n%s' % (construct_import_list(other_imports), contents)
    # wrap the contents in directory modules
    lib_parts = lib.split('.')
    contents = 'Module %s.\n%s\nEnd %s.\n' % (lib_parts[-1], contents, lib_parts[-1])
    for name in reversed(lib_parts[:-1]):
        contents = 'Module %s.\n%s\nEnd %s.\n' % (name, contents, name) # or Module Export?
#    existing_imports = recreate_path_structure((i, escape_lib(i)) for i in other_imports],
#                                               module_include=module_include,
#                                               uid=module_name,
#                                               topname=topname)
#    contents = 'Module %s.\n%s\n%s\nEnd %s.\n' % (module_name, existing_imports, contents, module_name)
    contents = 'Module %s.\n%s\nEnd %s.\n' % (module_name, contents, module_name)
    return contents


def include_imports(filename, as_modules=True, module_include='Include', verbose=DEFAULT_VERBOSE, fast=False, log=DEFAULT_LOG, topname='__TOP__', coqc='coqc', **kwargs):
    """Return the contents of filename, with any top-level imports inlined.

    If as_modules == True, then the imports will be wrapped in modules.

    This method requires access to the coqdep program if fast == False.
    Without it, it will fall back to manual parsing of the imports,
    which may change behavior.

    >>> import tempfile, os
    >>> f = tempfile.NamedTemporaryFile(dir='.', suffix='.v', delete=False)
    >>> g = tempfile.NamedTemporaryFile(dir='.', suffix='.v', delete=False)
    >>> g_name = os.path.relpath(g.name, '.')[:-2]
    >>> f.write("  Require  Import %s Coq.Init.Logic Arith.\n  Require  Export \tPArith\t Coq.Init.Logic.\n  Require Bool.\n Import Bool. (* asdf *)\n Require Import QArith\n  ZArith\n  Setoid.\nRequire Import %s.\n Require\n  Import\n%s\n\n\t.\t(*foo*)\n\nInductive t := a | b.\n\n(*asdf*)" % (g_name, g_name, g_name))
    >>> g.write(r"Require Export Ascii String.\n\nInductive q := c | d.")
    >>> f.close()
    >>> g.close()
    >>> print(include_imports(f.name, as_modules=False, verbose=False))
    Require Import Coq.Arith.Arith Coq.Bool.Bool Coq.Init.Logic Coq.PArith.PArith Coq.QArith.QArith Coq.Setoids.Setoid Coq.ZArith.ZArith Coq.Strings.Ascii Coq.Strings.String.

    Inductive q := c | d.
    (* asdf *)


    Inductive t := a | b.

    (*asdf*)

    >>> print(include_imports(f.name, as_modules=False, fast=True, verbose=False))
    Require Import Arith Bool Coq.Init.Logic PArith QArith Setoid ZArith Ascii String.

    Inductive q := c | d.
    (* asdf *)


    Inductive t := a | b.

    (*asdf*)
    >>> exts = ('.v', '.v.d', '.glob', '.vo', '.o', '.cmi', '.cmxs', '.native', '.cmx')
    >>> names = [f.name[:-2] + ext for ext in exts] + [g.name[:-2] + ext for ext in exts]
    >>> names = [i for i in names if os.path.exists(i)]
    >>> for name in names: os.remove(name)
    """
    if filename[-2:] != '.v': filename += '.v'
    lib = lib_of_filename(filename, topname=topname)
    all_imports = recursively_get_imports(lib, verbose=verbose, fast=fast, log=log, topname=topname, coqc=coqc)
    remaining_imports = []
    rtn = ''
    imports_done = []
    for import_name in all_imports:
        try:
            if as_modules:
                rtn += contents_as_module_without_require(import_name, imports_done, module_include=module_include, verbose=verbose, log=log, topname=topname) + '\n'
            else:
                rtn += contents_without_imports(import_name, verbose=verbose, log=log, topname=topname) + '\n'
            imports_done.append(import_name)
        except IOError:
            remaining_imports.append(import_name)
    if len(remaining_imports) > 0:
        if verbose:
            log('remaining imports:')
            log(remaining_imports)
        if as_modules:
            pattern = 'Require %s.\n%s'
        else:
            pattern = 'Require Import %s.\n%s'
        rtn = pattern % (' '.join(remaining_imports), rtn)
    return rtn

if __name__ == "__main__":
    # if we're working in python 3.3, we can test this file
    try:
        import doctest
        success = True
    except ImportError:
        print('This is not the main file to use.\nOnly run it if you have doctest (python 3.3+) and are testing things.')
        success = False
    if success:
        doctest.testmod()
