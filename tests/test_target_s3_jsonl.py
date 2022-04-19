'''Tests for the target_s3_jsonl.main module'''
# Standard library imports
from datetime import datetime as dt, timezone

# Third party imports
from pytest import fixture, raises
import boto3
from moto import mock_s3

from target import (
    sys,
    datetime,
    argparse,
    json,
    save_jsonl_file,
)

# Package imports
from target_s3_jsonl import (
    Path,
    run,
    upload_files,
    get_s3_config,
    main,
)


@fixture
def patch_datetime(monkeypatch):

    class mydatetime:
        @classmethod
        def utcnow(cls):
            return dt.fromtimestamp(1628663978.321056, tz=timezone.utc).replace(tzinfo=None)

        @classmethod
        def now(cls, x=timezone.utc, tz=None):
            return cls.utcnow()

        @classmethod
        def utcfromtimestamp(cls, x):
            return cls.utcnow()

        @classmethod
        def fromtimestamp(cls, x, format):
            return cls.utcnow()

        @classmethod
        def strptime(cls, x, format):
            return dt.strptime(x, format)

    monkeypatch.setattr(datetime, 'datetime', mydatetime)


@fixture
def patch_argument_parser(monkeypatch):

    class argument_parser:

        def __init__(self):
            self.config = str(Path('tests', 'resources', 'config.json'))

        def add_argument(self, x, y, help='Dummy config file', required=False):
            pass

        def parse_args(self):
            return self

    monkeypatch.setattr(argparse, 'ArgumentParser', argument_parser)


@fixture
def config():
    '''Use custom configuration set'''

    return {
        'date_time': dt.strptime('2021-08-11 06:39:38.321056+00:00', '%Y-%m-%d %H:%M:%S.%f%z'),
        'add_metadata_columns': False,
        'aws_access_key_id': 'ACCESS-KEY',
        'aws_secret_access_key': 'SECRET',
        's3_bucket': 'BUCKET',
        'work_dir': 'tests/output',
        'work_path': Path('tests/output'),
        'memory_buffer': 2000000,
        'compression': 'none',
        'timezone_offset': 0,
        'path_template': '{stream}-{date_time:%Y%m%dT%H%M%S}.jsonl',
        # 'path_template_default': '{stream}-{date_time:%Y%m%dT%H%M%S}.json',
        'open_func': open
    }


@fixture
def input_multi_stream_data():
    '''Use custom parameters set'''

    with open(Path('tests', 'resources', 'messages-with-three-streams.json'), 'r', encoding='utf-8') as input_file:
        return [item for item in input_file]


@fixture
def state():
    '''Use expected state'''

    return {
        'currently_syncing': None,
        'bookmarks': {
            'tap_dummy_test-test_table_one': {'initial_full_table_complete': True},
            'tap_dummy_test-test_table_two': {'initial_full_table_complete': True},
            'tap_dummy_test-test_table_three': {'initial_full_table_complete': True}}}


@fixture
def file_metadata():
    '''Use expected metadata'''

    return {
        'tap_dummy_test-test_table_one': {
            'relative_path': 'tap_dummy_test-test_table_one-20210811T063938.jsonl',
            'absolute_path': Path('tests/output/tap_dummy_test-test_table_one-20210811T063938.jsonl'),
            'file_data': []},
        'tap_dummy_test-test_table_two': {
            'relative_path': 'tap_dummy_test-test_table_two-20210811T063938.jsonl',
            'absolute_path': Path('tests/output/tap_dummy_test-test_table_two-20210811T063938.jsonl'),
            'file_data': []},
        'tap_dummy_test-test_table_three': {
            'relative_path': 'tap_dummy_test-test_table_three-20210811T063938.jsonl',
            'absolute_path': Path('tests/output/tap_dummy_test-test_table_three-20210811T063938.jsonl'),
            'file_data': [
                '{"c_pk": 1, "c_varchar": "1", "c_int": 1, "c_time": "04:00:00"}\n',
                '{"c_pk": 2, "c_varchar": "2", "c_int": 2, "c_time": "07:15:00"}\n',
                '{"c_pk": 3, "c_varchar": "3", "c_int": 3, "c_time": "23:00:03"}\n']}}


def clear_dir(dir_path):
    for path in dir_path.iterdir():
        path.unlink()
    dir_path.rmdir()


def test_get_s3_config(monkeypatch, patch_datetime, config):
    '''TEST : extract and enrich the configuration'''

    date_time = dt.strptime('2021-08-11 06:39:38.321056+00:00', '%Y-%m-%d %H:%M:%S.%f%z').replace(tzinfo=None)
    config_date_time = {'date_time': date_time}
    assert get_s3_config(str(Path('tests', 'resources', 'config.json'))) == config | config_date_time

    # NOTE: work around the random temporary working dir
    config_work_dir = {'work_dir': 'tests/output', 'work_path': Path('tests/output')}
    assert get_s3_config(str(Path('tests', 'resources', 'config_naked.json'))) \
        | config_work_dir == {
        's3_bucket': 'BUCKET',
        'path_template': '{stream}-{date_time:%Y%m%dT%H%M%S}.json',
        'memory_buffer': 64e6,
        'compression': 'none',
        # 'path_template_default': '{stream}-{date_time:%Y%m%dT%H%M%S}.json',
        'open_func': open
    } | config_date_time | config_work_dir

    with raises(Exception):
        get_s3_config(str(Path('tests', 'resources', 'config_no_bucket.json')))


@mock_s3
def test_upload_files(config, file_metadata):
    '''TEST : simple upload_files call'''

    Path(config['work_dir']).mkdir(parents=True, exist_ok=True)
    for _, file_info in file_metadata.items():
        run(save_jsonl_file(None, {'open_func': open}, file_info))

    conn = boto3.resource('s3', region_name='us-east-1')
    conn.create_bucket(Bucket=config['s3_bucket'])

    upload_files(file_metadata, config)

    assert not file_metadata['tap_dummy_test-test_table_three']['absolute_path'].exists()

    clear_dir(Path(config['work_dir']))


@mock_s3
def test_main(monkeypatch, capsys, patch_datetime, patch_argument_parser, input_multi_stream_data, config, state, file_metadata):
    '''TEST : simple main call'''

    monkeypatch.setattr(sys, 'stdin', input_multi_stream_data)

    conn = boto3.resource('s3', region_name='us-east-1')
    conn.create_bucket(Bucket=config['s3_bucket'])

    main()

    captured = capsys.readouterr()
    assert captured.out == json.dumps(state) + '\n'

    for _, file_info in file_metadata.items():
        assert not file_info['absolute_path'].exists()

    class argument_parser:

        def __init__(self):
            self.config = str(Path('tests', 'resources', 'config_local.json'))

        def add_argument(self, x, y, help='Dummy config file', required=False):
            pass

        def parse_args(self):
            return self

    monkeypatch.setattr(argparse, 'ArgumentParser', argument_parser)

    main()

    captured = capsys.readouterr()
    assert captured.out == json.dumps(state) + '\n'

    for _, file_info in file_metadata.items():
        assert file_info['absolute_path'].exists()

    clear_dir(config['work_path'])