# -*- coding: utf-8 -*-
import sys
import argparse
import ConfigParser


class Config(object):

    instance = None

    def __init__(self):
        # Load specified configuration file
        parser = argparse.ArgumentParser(
            description="""This services provides a user space filesystem overlay for dynamically
generated PXE configurations. It takes a static directory and provides the
files from that directory on a newly mounted path - which gets filtered by
a set of plugins that can provide drop in configurations for certain MAC
addresses.""",
            prog='fts',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument('--config', '-c',
            metavar='FILE',
            help='path to the configuration file', default="/etc/fts/config")
        parser.add_argument('--foreground', '-f',
            action='store_true', help='path to the configuration file')

        cli_opts = parser.parse_args()
        config = ConfigParser.ConfigParser()
        config.read(cli_opts.config)
        if not config.has_section('core'):
            config.add_section('core')
        if cli_opts.foreground:
            config.set('core', 'foreground', 'True')

        self.__config = config

        # Reset command line
        sys.argv = [sys.argv[0]]

    def get(self, path, default=None):
        section, key = path.split(".")[0:2]
        try:
            return self.__config.get(section, key)

        except:
            pass

        return default

    @staticmethod
    def get_instance():
        if not Config.instance:
            Config.instance = Config()

        return Config.instance
