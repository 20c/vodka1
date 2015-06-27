
from setuptools import setup

version = open('config/VERSION').read().strip()
requirements = open('config/requirements.txt').read().split("\n")

setup(
    name='twentyc.vodka',
    version=version,
    author='Twentieth Century',
    author_email='code@20c.com',
    description='vodka wsgi framework with xbahn support',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    packages=[
      'twentyc.vodka',
      'twentyc.vodka.tools',
      'twentyc.vodka.wsgi'
    ],
    namespace_packages=['twentyc'],
    scripts=['bin/bartender'],
    include_package_data=True,
    install_requires=requirements,
    zip_safe=False
)
