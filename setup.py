#!/usr/bin/python -u
#
# Python Bindings for XZ/LZMA backported from Python 3.3.0
#
# This file copyright (c) 2012 Peter Cock, p.j.a.cock@googlemail.com
# See other files for separate copyright notices.

import sys, os
from warnings import warn

from setuptools import setup
from setuptools.command.build_ext import build_ext
from setuptools.extension import Extension

# We now extract the version number in lzmaffi/__init__.py
# We can't use "from backports import lzma" then "lzma.__version__"
# as that would tell us the version already installed (if any).
__version__ = None
with open('lzmaffi/__init__.py') as handle:
    for line in handle:
        if (line.startswith('__version__')):
            exec(line.strip())
            break
if __version__ is None:
    sys.stderr.write("Error getting __version__ from lzmaffi/__init__.py\n")
    sys.exit(1)
print("This is lzmaffi version %s" % __version__)

if 'egg_info' not in sys.argv:
	import lzmaffi._lzmamodule2 as ffimod

	packages = ["lzmaffi",
			"_lzmaffi_mods"] # workaround for https://bitbucket.org/cffi/cffi/issue/109/enable-sane-packaging-for-cffi
	extens = [ffimod.ffi.verifier.get_extension()]
else:
	packages = ["lzmaffi", "_lzmaffi_mods"]
	extens = []

descr = "Port of Python 3.3's 'lzma' module for XZ/LZMA compressed files to cffi."
long_descr = """This is a port of the 'lzma' module included in Python 3.3 or later
by Nadeem Vawda and Per Oyvind Karlsen, which provides a Python wrapper for XZ Utils
(aka LZMA Utils v2) by Igor Pavlov.

Unlike backports.lzma which is a straight backport, this version uses cffi which means
it runs on PyPy without having to use the (very slow) CPyExt. It also runs perfectly
well on CPython 2.6, 2.7 or 3.

To use, either `import lzmaffi as lzma', or add this at the beginning of your script:

import lzmaffi.compat
lzmaffi.compat.register()

Then `import lzma' as usual.

In order to compile this, you will need to install XZ Utils from http://tukaani.org/xz/
"""

if sys.version_info < (2,6):
    sys.stderr.write("ERROR: Python 2.5 and older are not supported, and never will be.\n")
    sys.exit(1)
if sys.version_info < (2,7):
    sys.stderr.write("ERROR: Python 2.6 is only compatible in versions under 0.2.0.\n")
    sys.exit(1)

setup(
    name = "lzmaffi",
    version = __version__,
    description = descr,
    ext_package='_lzmaffi_mods',
    author = "Tomer Chachamu, based on work by Peter Cock",
    author_email = "tomer.chachamu@gmail.com",
    url = "https://github.com/r3m0t/backports.lzma",
    license='3-clause BSD License',
    keywords = "xz lzma compression decompression cffi ffi",
    long_description = long_descr,
    install_requires=['cffi>=0.6'],
    zip_safe=False,
    classifiers = [
        'Development Status :: 5 - Production/Stable',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        #'Operating System :: OS Independent',
        'Topic :: System :: Archiving :: Compression',
    ],
    packages = packages,
    ext_modules = extens,
    cmdclass = {
        'build_ext': build_ext,
    },
)
