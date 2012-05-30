#!/usr/bin/env python

import os
import os.path
import sys

VERSION = (0, 1, 0)


class BuildException(Exception):
    pass

class DepNode(object):
    def __init__(self, module=None, file_name=None, is_module=True):
        self.module = module
        self.file_name = file_name
        self.is_module = is_module
        self.loaded = False
        self.content = ""

        # For dependency graph
        self.dependencies = []
        self.dependents = []
        self.visited = False

    def push_dependency(self, dep):
        self.dependencies.append(dep)
        dep.dependents.append(self)

    def get_file_suffix(self):
        if self.file_name is not None:
            name, ext = os.path.splitext(self.file_name)
            return ext

    def __str__(self):
        return '%s (%s)' % (self.module, self.file_name)


class DepGraph(object):
    def __init__(self):
        self.leaves = []
        self.all_nodes = []

    def build(self, inputs, sources):
        import re

        cache = {}
        queue = [DepNode(file_name=f) for f in inputs]

        def has_node(mod_name, only_if_loaded=False):
            "Checks the cache for a node representing a module by this name"
            if mod_name in cache:
                if only_if_loaded and not cache[mod_name].loaded:
                    return False
                else:
                    return True
            else:
                return False

        def get_node(mod_name):
            "Checks the cache for a node representing this module, or creates a new one"
            if not has_node(mod_name):
                node = DepNode(mod_name)
                self.all_nodes.append(node)
                cache[mod_name] = node

            return cache[mod_name]

        def guess_file(node):
            "Guesses which file contains a particular module from it's file name"
            fields = node.module.split('.')
            mod_name = fields[-1]
            file_name = '%s.js' % mod_name
            for source in sources:
                if os.path.basename(source) == file_name:
                    return source

        def add_node_dep(node, dep_name):
            existed = has_node(dep_name)
            dep = get_node(dep_name)
            node.push_dependency(dep)

            # If this was a newly encountered module, add it
            # to the queue to try to load it (and any further
            # dependencies that it might have)
            if not existed:
                queue.append(dep)


        mod_re = re.compile('away3d\.module\(\s?["\']([_a-zA-Z0-9.]*)["\']\s?,\s?(.*),\s?function\(\)\s?\{(.*)\}\s?\)\s?;?\s?$', re.DOTALL)
        dep_re = re.compile('["\']([a-zA-Z0-9.]+)["\']')
        inc_re = re.compile('away3d\.include\(\s*(.*),\s*function\(\s*\)', re.DOTALL)

        for node in queue:
            # Check if this node has already been checked since
            # it was added to the queue.
            if has_node(node.module, only_if_loaded=True):
                continue

            fname = node.file_name or guess_file(node)
            if fname is None or not os.path.isfile(fname):
                raise BuildException('Could not find file for module %s' % node.module)

            with open(fname, 'r') as f:
                buf = f.read()
                m = re.search(mod_re, buf)

                if m is not None:
                    name = m.group(1)
                    dep_arg = m.group(2).strip()

                    node = get_node(name)
                    node.file_name = fname
                    node.content = m.group(3)
                    node.loaded = True

                    dep_names = re.findall(dep_re, dep_arg)

                    for dep_name in dep_names:
                        add_node_dep(node, dep_name)


                else:
                    # Not a module file, but it might still contain include
                    # statements and hence have dependencies.
                    m = re.search(inc_re, buf)
                    if m is not None:
                        dep_arg = m.group(1)
                        dep_names = re.findall(dep_re, dep_arg)
                        if len(dep_names) > 0:
                            # This is not a proper module, so using file name
                            # as module name.
                            file_node = get_node(fname)
                            file_node.file_name = fname
                            file_node.is_module = False

                            for dep_name in dep_names:
                                add_node_dep(node, dep_name)
        

        # Leaves list should contain all leaf nodes, i.e. nodes that do
        # not have any dependencies.
        for node in self.all_nodes:
            if len(node.dependencies) == 0:
                self.leaves.append(node)

        return self.leaves



    def evaluate_chain(self):
        chain = []

        def visit(node):
            if not node.visited:
                node.visited = True
                for dep in node.dependents:
                    visit(dep)
                chain.insert(0, node)

        for node in self.leaves:
            visit(node)

        return chain


def find_js_files(path):
    # In the special case that path is a file, the user should probably
    # be trusted with using this file, even if it's suffix is not js
    if os.path.isfile(path):
        return [path]

    found = []
    def visit(arg, dirname, names):
        for name in names:
            base, ext = os.path.splitext(name)
            if ext == '.js':
                found.append(os.path.join(dirname, name))

    os.path.walk(path, visit, None)
    return found
    



def get_output_file(output):
    if output is None:
        return sys.stdout
    else:
        return open(output, 'w')

def listdep(graph, output):
    "List module dependencies in order of dependency."
    output = get_output_file(output)
    chain = graph.evaluate_chain()
    for node in chain:
        output.write('%s\n' % node)

def concat(graph, output):
    "Concatenate module files in order of dependency."
    output = get_output_file(output)
    chain = graph.evaluate_chain()
    for node in chain:
        name, ext = os.path.splitext(node.file_name)
        if ext == '.js':
            #TODO: Support different output formats
            output.write('// %s\n' % node.file_name)
            output.write('%s = (function() {\n' % node.module)
            output.write(node.content.lstrip('\n'))
            output.write('})();\n\n')

def gather(graph, output):
    "Copy dependency module files to a common directory."
    if output is not None and os.path.isdir(output):
        import shutil

        for node in graph.all_nodes:
            fname = os.path.basename(node.file_name)
            dst = os.path.join(output, fname)
            print('Copying %s > %s' % (node.file_name, dst))
            shutil.copyfile(node.file_name, dst)

    else:
        raise BuildException('Output must be directory')

def printhelp():
    print('')
    print('Away3D.js build tool, version %d.%d.%d' % VERSION)
    print('')
    print('Commands available:')
    print('  help       Print this message.')
    for key, val in commands.items():
        print('  %s %s' % (key.ljust(10), val.__doc__))

    print('')
    print('Options available:')
    print('  -i <path>  Specifies a required input.')
    print('  -s <path>  Specifies a path to search for dependencies.')
    print('  -o <path>  Specifies output file or directory.')
    print('')


# These are the commands that the tool supports (excluding the help command)
commands = {
    'list': listdep,
    'concat': concat,
    'gather': gather,
}

if __name__ == '__main__':
    if len(sys.argv) > 1:

        cmd = sys.argv[1]
        if cmd == 'help':
            printhelp()
        else:
            if cmd in commands:
                import getopt

                inputs = []
                sources = []
                output = None

                opts, extras = getopt.getopt(sys.argv[2:], 's:i:o:')

                for opt in opts:
                    if opt[0] == '-i':
                        inputs.extend(find_js_files(opt[1]))
                    elif opt[0] == '-s':
                        sources.extend(find_js_files(opt[1]))
                    elif opt[0] == '-o':
                        output = opt[1]

                try:
                    graph = DepGraph()
                    graph.build(inputs, sources)
                    commands[cmd](graph, output)

                except BuildException as e:
                    print('Error: %s' % e)
            else:
                print('Unknown command: %s' % cmd)
                sys.exit(-1)

    else:
        printhelp()
