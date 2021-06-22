import argparse

from hart import utils as uut

def test_remove_argument_from_parser_single_flag():
    parser = argparse.ArgumentParser()
    parser.add_argument('--foo')
    assert '--foo' in parser.format_usage()

    uut.remove_argument_from_parser(parser, '--foo')

    assert '--foo' not in parser.format_usage()

    # This shouldn't crash
    parser.add_argument('--foo', help='Something')


def test_remove_argument_from_parser_multiple_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--foo')
    assert '-f' in parser.format_usage()

    uut.remove_argument_from_parser(parser, '--foo')

    assert '-f' not in parser.format_usage()
    assert '--foo' not in parser.format_usage()

    # This shouldn't crash
    parser.add_argument('-f', '--foo', help='Something')
