import os
import io
import shutil

from demisto_sdk.test_playbook_generator.test_playbook_generator import TestPlaybookGenerator


def load_file_from_test_dir(filename):
    with io.open(os.path.join('tests', 'test_files', filename), mode='r', encoding='utf-8') as f:
        return f.read()


class TestGenerateTestPlaybook:
    TEMP_DIR = 'temp'
    CREATED_DIRS = list()

    @classmethod
    def setup_class(cls):
        print("Setups TestGenerateTestPlaybook class")
        if not os.path.exists(TestGenerateTestPlaybook.TEMP_DIR):
            os.mkdir(TestGenerateTestPlaybook.TEMP_DIR)

    @classmethod
    def teardown_class(cls):
        print("Tearing down TestGenerateTestPlaybook class")
        if os.path.exists(TestGenerateTestPlaybook.TEMP_DIR):
            shutil.rmtree(TestGenerateTestPlaybook.TEMP_DIR, ignore_errors=False, onerror=None)

    def test_generate_test_playbook(self):
        generator = TestPlaybookGenerator(
            infile='tests/test_files/fake_integration.yml',
            outdir=TestGenerateTestPlaybook.TEMP_DIR,
            name='TestPlaybook'
        )

        generator.run()

        with io.open(os.path.join('tests', 'test_files', 'fake_integration_expected_test_playbook.yml'), mode='r',
                     encoding='utf-8') as f:
            expected_test_playbook_yml = f.read()

        with io.open(os.path.join(TestGenerateTestPlaybook.TEMP_DIR, 'TestPlaybook.yml'), mode='r',
                     encoding='utf-8') as f:
            actual_test_playbook_yml = f.read()

        assert expected_test_playbook_yml == actual_test_playbook_yml