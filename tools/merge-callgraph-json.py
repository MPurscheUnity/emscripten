import json, os, sys, subprocess, shlex

def read_response_file(response_filename):
  """Reads a response file, and returns the list of cmdline params found in the
  file.

  The encoding that the response filename should be read with can be specified
  as a suffix to the file, e.g. "foo.rsp.utf-8" or "foo.rsp.cp1252". If not
  specified, first UTF-8 and then Python locale.getpreferredencoding() are
  attempted.

  The parameter response_filename may start with '@'."""
  if response_filename.startswith('@'):
    response_filename = response_filename[1:]

  if not os.path.exists(response_filename):
    raise IOError("response file not found: %s" % response_filename)

  # Guess encoding based on the file suffix
  components = os.path.basename(response_filename).split('.')
  encoding_suffix = components[-1].lower()
  if len(components) > 1 and (encoding_suffix.startswith('utf') or encoding_suffix.startswith('cp') or encoding_suffix.startswith('iso') or encoding_suffix in ['ascii', 'latin-1']):
    guessed_encoding = encoding_suffix
  else:
    # On windows, recent version of CMake emit rsp files containing
    # a BOM.  Using 'utf-8-sig' works on files both with and without
    # a BOM.
    guessed_encoding = 'utf-8-sig'

  try:
    # First try with the guessed encoding
    with open(response_filename, encoding=guessed_encoding) as f:
      args = f.read()
  except (ValueError, LookupError): # UnicodeDecodeError is a subclass of ValueError, and Python raises either a ValueError or a UnicodeDecodeError on decode errors. LookupError is raised if guessed encoding is not an encoding.
    # If that fails, try with the Python default locale.getpreferredencoding()
    with open(response_filename) as f:
      args = f.read()

  args = shlex.split(args)

  return args

def substitute_response_files(args):
  """Substitute any response files found in args with their contents."""
  new_args = []
  for arg in args:
    if arg.startswith('@'):
      new_args += read_response_file(arg)
    elif arg.startswith('-Wl,@'):
      for a in read_response_file(arg[5:]):
        if a.startswith('-'):
          a = '-Wl,' + a
        new_args.append(a)
    else:
      new_args.append(arg)
  return new_args

args = substitute_response_files(sys.argv[1:])

def extract_arg(optname):
  global args
  for i in range(len(args)):
    if args[i] == optname:
      output = args[i+1]
      args = args[:i] + args[i+2:]
      return output

out_json_filename = extract_arg('-o')
wasm_output_name = extract_arg('--wasm')

wasm_module_function_names = None
if wasm_output_name:
  wasm_module_function_names = []
  wasm_fnames = subprocess.check_output(["wasm-opt", "--nm", wasm_output_name]).decode('utf-8')
  for line in wasm_fnames.split('\n'):
    if ':' in line:
      fname = line.split(':')[0].strip()
#      print(str(fname))
      wasm_module_function_names += [fname]
  #print(str(wasm_fnames))
#  sys.exit(1)

print('Merging ' + str(len(args)) + ' call graphs into one output: ' + out_json_filename)

graphs = []
for i in args:
  graphs += [json.load(open(i))]

filenames = {'': 0}

def record_filename(filename):
  assert filename != None
  if filename in filenames:
    return filenames[filename]
  id = len(filenames.keys())
  filenames[filename] = id
  return id

function_names = {'': 0}

def record_function_name(function_name):
  if function_name in function_names:
    return function_names[function_name]
  id = len(function_names.keys())
  function_names[function_name] = id
  return id

functions = []

# Merge all functions
for g in graphs:
  g_function_names = g['functionNames']
  g_filenames = g['filenames']
  for f in g['functions']:
#    print(str(f))
    name = g_function_names[f['n']]
    if wasm_module_function_names is not None and name not in wasm_module_function_names:
      continue
    name_number = record_function_name(name)
    filename = g_filenames[f['f']] if 'f' in f else None
    filename_number = record_filename(filename) if filename else 0
    line_number = f['l'] if 'l' in f else None

    callees = []
    callees_seen = set() # Deduplicate entries of a function calling another function several times
    if 'c' in f:
      for c in f['c']:
        if c['n'] in callees_seen:
          continue
        callees_seen.add(c['n'])
        callee_function_name = g_function_names[c['n']]
        callee_function_name_number = record_function_name(callee_function_name)
        call_line = c['l'] if 'l' in c else None
        call_column = c['c'] if 'c' in c else None
        callee = {
          'n': callee_function_name_number
        }
        if call_line: callee['l'] = call_line
        if call_column: callee['c'] = call_column
        callees += [callee]

    function = {
      'n': name_number
    }
    if filename_number: function['f'] = filename_number
    if line_number: function['l'] = line_number

    if len(callees) > 0:
      function['c'] = callees

    functions += [function]

def dict_to_linear_array(d):
  arr = ['']*len(d.keys())
  for key in d:
    arr[d[key]] = key
  return arr

output_json = {
  'functionNames': dict_to_linear_array(function_names),
  'filenames': dict_to_linear_array(filenames),
  'functions': functions
}

open(out_json_filename, 'w').write(json.dumps(output_json))
