"""
This script is used to validate the files in Content repository. Specifically for each file:
1) Proper prefix
2) Proper suffix
3) Valid yml/json schema
4) Having ReleaseNotes if applicable.

It can be run to check only committed changes (if the first argument is 'true') or all the files in the repo.
Note - if it is run for all the files in the repo it won't check releaseNotes, use `release_notes.py`
for that task.
"""
from __future__ import print_function
import os
import glob

# TODO: do not import *
from ..common.constants import *
from ..common.hook_validations.id import IDSetValidator
from ..common.hook_validations.image import ImageValidator
from ..yaml_tools.unifier import Unifier
from ..common.hook_validations.script import ScriptValidator
from ..common.hook_validations.conf_json import ConfJsonValidator
from ..common.hook_validations.structure import StructureValidator
from ..common.hook_validations.integration import IntegrationValidator
from ..common.hook_validations.description import DescriptionValidator
from ..common.hook_validations.incident_field import IncidentFieldValidator
from ..common.tools import checked_type, run_command, print_error, print_warning, print_color, LOG_COLORS, \
    get_yaml, filter_packagify_changes, collect_ids, str2bool
from ..common.configuration import Configuration


class FilesValidator:
    """FilesValidator is a class that's designed to validate all the changed files on your branch, and all files in case
    you are on master, this class will be used on your local env as the validation hook(pre-commit), and on CircleCi
    to make sure you did not bypass the hooks as a safety precaution.

    Attributes:
        _is_valid (bool): saves the status of the whole validation(instead of mingling it between all the functions).
        conf_json_validator (ConfJsonValidator): object for validating the conf.json file.
        id_set_validator (IDSetValidator): object for validating the id_set.json file(Created in Circle only).
    """

    def __init__(self, is_backward_check=True, prev_ver='origin/master', use_git=True, is_circle=False,
                 print_ignored_files=False, validate_conf_json=True, validate_id_set=False,
                 configuration=Configuration()):
        self.branch_name = ''
        self.use_git = use_git
        if self.use_git:
            branches = run_command('git branch')
            branch_name_reg = re.search(r'\* (.*)', branches)
            self.branch_name = branch_name_reg.group(1)

        self.prev_ver = prev_ver
        if not self.prev_ver:
            # validate against master if no version was provided
            self.prev_ver = 'origin/master'

        self._is_valid = True
        self.configuration = configuration
        self.is_backward_check = is_backward_check
        self.is_circle = is_circle
        self.print_ignored_files = print_ignored_files
        self.validate_conf_json = validate_conf_json
        self.validate_id_set = validate_id_set

        if self.validate_conf_json:
            self.conf_json_validator = ConfJsonValidator()
        if self.validate_id_set:
            self.id_set_validator = IDSetValidator(is_circle=self.is_circle, configuration=self.configuration)

    @staticmethod
    def get_modified_files(files_string, tag='master', print_ignored_files=False):
        """Get lists of the modified files in your branch according to the files string.

        Args:
            files_string (string): String that was calculated by git using `git diff` command.
            tag (string): String of git tag used to update modified files.
            print_ignored_files (bool): should print ignored files.

        Returns:
            (modified_files_list, added_files_list, deleted_files). Tuple of sets.
        """
        all_files = files_string.split('\n')
        deleted_files = set([])
        added_files_list = set([])
        modified_files_list = set([])
        old_format_files = set([])
        for f in all_files:
            file_data = f.split()
            if not file_data:
                continue

            file_status = file_data[0]
            file_path = file_data[1]

            if file_status.lower().startswith('r'):
                file_status = 'r'
                file_path = file_data[2]

            if checked_type(file_path, CODE_FILES_REGEX) and file_status.lower() != 'd' \
                    and not file_path.endswith('_test.py'):
                # naming convention - code file and yml file in packages must have same name.
                file_path = os.path.splitext(file_path)[0] + '.yml'
            elif file_path.endswith('.js') or file_path.endswith('.py'):
                continue

            if file_status.lower() in ['m', 'a', 'r'] and checked_type(file_path, OLD_YML_FORMAT_FILE) and \
                    FilesValidator._is_py_script_or_integration(file_path):
                old_format_files.add(file_path)
            elif file_status.lower() == 'm' and checked_type(file_path) and not file_path.startswith('.'):
                modified_files_list.add(file_path)
            elif file_status.lower() == 'a' and checked_type(file_path) and not file_path.startswith('.'):
                added_files_list.add(file_path)
            elif file_status.lower() == 'd' and checked_type(file_path) and not file_path.startswith('.'):
                deleted_files.add(file_path)
            elif file_status.lower().startswith('r') and checked_type(file_path):
                # if a code file changed, take the associated yml file.
                if checked_type(file_data[2], CODE_FILES_REGEX):
                    modified_files_list.add(file_path)
                else:
                    modified_files_list.add((file_data[1], file_data[2]))

            elif checked_type(file_path, [SCHEMA_REGEX]):
                modified_files_list.add(file_path)

            elif file_status.lower() not in KNOWN_FILE_STATUSES:
                print_error('{} file status is an unknown known one, please check. File status was: {}'.format(
                    file_path, file_status))

            elif print_ignored_files and not checked_type(file_path, IGNORED_TYPES_REGEXES):
                print_warning('Ignoring file path: {}'.format(file_path))

        modified_files_list, added_files_list, deleted_files = filter_packagify_changes(
            modified_files_list,
            added_files_list,
            deleted_files,
            tag)

        return modified_files_list, added_files_list, deleted_files, old_format_files

    def get_modified_and_added_files(self, tag='origin/master'):
        """Get lists of the modified and added files in your branch according to the git diff output.

        Args:
            tag (string): String of git tag used to update modified files

        Returns:
            (modified_files, added_files). Tuple of sets.
        """
        # Two dots is the default in git diff, it will compare with the last known commit as the base
        # Three dots will compare with the last known shared commit as the base
        compare_type = '.' if 'master' in tag else ''
        all_changed_files_string = run_command(
            'git diff --name-status {tag}..{compare_type}refs/heads/{branch}'.format(tag=tag,
                                                                                     branch=self.branch_name,
                                                                                     compare_type=compare_type))
        modified_files, added_files, _, old_format_files = self.get_modified_files(
            all_changed_files_string,
            tag=tag,
            print_ignored_files=self.print_ignored_files)

        if not self.is_circle:
            files_string = run_command('git diff --name-status --no-merges HEAD')
            non_committed_modified_files, non_committed_added_files, non_committed_deleted_files, \
                non_committed_old_format_files = self.get_modified_files(
                    files_string, print_ignored_files=self.print_ignored_files)

            all_changed_files_string = run_command('git diff --name-status {}'.format(tag))
            modified_files_from_tag, added_files_from_tag, _, _ = \
                self.get_modified_files(all_changed_files_string,
                                        print_ignored_files=self.print_ignored_files)

            old_format_files = old_format_files.union(non_committed_old_format_files)
            modified_files = modified_files.union(
                modified_files_from_tag.intersection(non_committed_modified_files))

            added_files = added_files.union(
                added_files_from_tag.intersection(non_committed_added_files))

            modified_files = modified_files - set(non_committed_deleted_files)
            added_files = added_files - set(non_committed_modified_files) - set(non_committed_deleted_files)

        return modified_files, added_files, old_format_files

    def validate_modified_files(self, modified_files):
        """Validate the modified files from your branch.

        In case we encounter an invalid file we set the self._is_valid param to False.

        Args:
            modified_files (set): A set of the modified files in the current branch.
        """
        for file_path in modified_files:
            old_file_path = None
            if isinstance(file_path, tuple):
                old_file_path, file_path = file_path

            print('Validating {}'.format(file_path))
            if not checked_type(file_path):
                print_warning('- Skipping validation of non-content entity file.')
                continue

            structure_validator = StructureValidator(file_path,
                                                     use_git=self.use_git,
                                                     is_added_file=self.branch_name and not
                                                     (False or self.is_backward_check),
                                                     is_renamed=self.branch_name and old_file_path is not None,
                                                     configuration=self.configuration)
            if not structure_validator.is_file_valid():
                self._is_valid = False
            if self.validate_id_set:
                if not self.id_set_validator.is_file_valid_in_set(file_path):
                    self._is_valid = False

            elif re.match(INTEGRATION_REGEX, file_path, re.IGNORECASE) or \
                    re.match(INTEGRATION_YML_REGEX, file_path, re.IGNORECASE):

                image_validator = ImageValidator(file_path)
                if not image_validator.is_valid():
                    self._is_valid = False

                description_validator = DescriptionValidator(file_path)
                if not description_validator.is_valid():
                    self._is_valid = False

                integration_validator = IntegrationValidator(file_path, old_file_path=old_file_path,
                                                             old_git_branch=self.prev_ver)
                if self.is_backward_check and not integration_validator.is_backward_compatible():
                    self._is_valid = False
                if not integration_validator.is_valid_integration():
                    self._is_valid = False

            elif re.match(BETA_INTEGRATION_REGEX, file_path, re.IGNORECASE) or \
                    re.match(BETA_INTEGRATION_YML_REGEX, file_path, re.IGNORECASE):
                description_validator = DescriptionValidator(file_path)
                if not description_validator.is_valid_beta_description():
                    self._is_valid = False
                integration_validator = IntegrationValidator(file_path, old_file_path=old_file_path)
                if not integration_validator.is_valid_beta_integration():
                    self._is_valid = False

            elif re.match(SCRIPT_REGEX, file_path, re.IGNORECASE):
                script_validator = ScriptValidator(file_path, old_file_path=old_file_path,
                                                   old_git_branch=self.prev_ver)
                if self.is_backward_check and not script_validator.is_backward_compatible():
                    self._is_valid = False
                if not script_validator.is_valid_script():
                    self._is_valid = False

            elif re.match(SCRIPT_YML_REGEX, file_path, re.IGNORECASE) or \
                    re.match(SCRIPT_PY_REGEX, file_path, re.IGNORECASE) or \
                    re.match(SCRIPT_JS_REGEX, file_path, re.IGNORECASE):

                unifier = Unifier(os.path.dirname(file_path))
                yml_path, _ = unifier.get_script_package_data()
                script_validator = ScriptValidator(yml_path, old_file_path=old_file_path,
                                                   old_git_branch=self.prev_ver)
                if self.is_backward_check and not script_validator.is_backward_compatible():
                    self._is_valid = False

            elif re.match(IMAGE_REGEX, file_path, re.IGNORECASE):
                image_validator = ImageValidator(file_path)
                if not image_validator.is_valid():
                    self._is_valid = False

            elif re.match(INCIDENT_FIELD_REGEX, file_path, re.IGNORECASE):
                incident_field_validator = IncidentFieldValidator(file_path, old_file_path=old_file_path,
                                                                  old_git_branch=self.prev_ver)
                if not incident_field_validator.is_valid():
                    self._is_valid = False
                if self.is_backward_check and not incident_field_validator.is_backward_compatible():
                    self._is_valid = False

    def validate_added_files(self, added_files):
        """Validate the added files from your branch.

        In case we encounter an invalid file we set the self._is_valid param to False.

        Args:
            added_files (set): A set of the modified files in the current branch.
        """
        for file_path in added_files:
            print('Validating {}'.format(file_path))

            structure_validator = StructureValidator(file_path, use_git=self.use_git,
                                                     is_added_file=True, configuration=self.configuration)
            if not structure_validator.is_file_valid():
                self._is_valid = False

            if self.validate_id_set:
                if not self.id_set_validator.is_file_valid_in_set(file_path):
                    self._is_valid = False

                if self.id_set_validator.is_file_has_used_id(file_path):
                    self._is_valid = False

            if re.match(TEST_PLAYBOOK_REGEX, file_path, re.IGNORECASE):
                if not self.conf_json_validator.is_test_in_conf_json(collect_ids(file_path)):
                    self._is_valid = False

            elif re.match(INTEGRATION_REGEX, file_path, re.IGNORECASE) or \
                    re.match(INTEGRATION_YML_REGEX, file_path, re.IGNORECASE) or \
                    re.match(IMAGE_REGEX, file_path, re.IGNORECASE):

                image_validator = ImageValidator(file_path)
                if not image_validator.is_valid():
                    self._is_valid = False

                description_validator = DescriptionValidator(file_path)
                if not description_validator.is_valid():
                    self._is_valid = False

                integration_validator = IntegrationValidator(file_path)
                if not integration_validator.is_valid_integration():
                    self._is_valid = False

            elif re.match(BETA_INTEGRATION_REGEX, file_path, re.IGNORECASE) or \
                    re.match(BETA_INTEGRATION_YML_REGEX, file_path, re.IGNORECASE):
                description_validator = DescriptionValidator(file_path)
                if not description_validator.is_valid_beta_description():
                    self._is_valid = False

                integration_validator = IntegrationValidator(file_path)
                if not integration_validator.is_valid_beta_integration(is_new=True):
                    self._is_valid = False
            elif re.match(IMAGE_REGEX, file_path, re.IGNORECASE):
                image_validator = ImageValidator(file_path)
                if not image_validator.is_valid():
                    self._is_valid = False

            elif re.match(INCIDENT_FIELD_REGEX, file_path, re.IGNORECASE):
                incident_field_validator = IncidentFieldValidator(file_path)
                if not incident_field_validator.is_valid():
                    self._is_valid = False

    def validate_no_old_format(self, old_format_files):
        """ Validate there are no files in the old format(unified yml file for the code and configuration).

        Args:
            old_format_files(set): file names which are in the old format.
        """
        invalid_files = []
        for f in old_format_files:
            yaml_data = get_yaml(f)
            if 'toversion' not in yaml_data:  # we only fail on old format if no toversion (meaning it is latest)
                invalid_files.append(f)
        if invalid_files:
            print_error('You should update the following files to the package format, for further details please visit '
                        'https://github.com/demisto/content/tree/master/docs/package_directory_structure. '
                        'The files are:\n{}'.format('\n'.join(list(invalid_files))))
            self._is_valid = False

    def validate_committed_files(self):
        """Validate that all the committed files in your branch are valid

        """
        modified_files, added_files, old_format_files = self.get_modified_and_added_files()
        schema_changed = False
        for f in modified_files:
            if isinstance(f, tuple):
                _, f = f
            if checked_type(f, [SCHEMA_REGEX]):
                schema_changed = True
        # Ensure schema change did not break BC
        if schema_changed:
            self.validate_all_files()
        else:
            self.validate_modified_files(modified_files)
            self.validate_added_files(added_files)
            self.validate_no_old_format(old_format_files)

    def validate_all_files(self):
        """Validate all files in the repo are in the right format."""
        for regex in CHECKED_TYPES_REGEXES:
            splitted_regex = regex.split('.*')
            directory = splitted_regex[0]
            for root, dirs, files in os.walk(directory):
                if root not in DIR_LIST:  # Skipping in case we entered a package
                    continue
                print_color('Validating {} directory:'.format(directory), LOG_COLORS.GREEN)
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    # skipping hidden files
                    if file_name.startswith('.'):
                        continue

                    print('Validating ' + file_name)
                    structure_validator = StructureValidator(file_path, use_git=self.use_git,
                                                             configuration=self.configuration)
                    if not structure_validator.is_valid_scheme():
                        self._is_valid = False

                if root in PACKAGE_SUPPORTING_DIRECTORIES:
                    for inner_dir in dirs:
                        file_path = glob.glob(os.path.join(root, inner_dir, '*.yml'))[0]
                        print('Validating ' + file_path)
                        structure_validator = StructureValidator(file_path, use_git=self.use_git,
                                                                 configuration=self.configuration)
                        if not structure_validator.is_valid_scheme():
                            self._is_valid = False

    def is_valid_structure(self):
        """Check if the structure is valid for the case we are in, master - all files, branch - changed files.

        Returns:
            (bool). Whether the structure is valid or not.
        """
        if self.validate_conf_json:
            if not self.conf_json_validator.is_valid_conf_json():
                self._is_valid = False
        if self.branch_name:
            if self.branch_name != 'master' and (not self.branch_name.startswith('19.') and
                                                 not self.branch_name.startswith('20.')):
                # validates only committed files
                self.validate_committed_files()
                self.validate_against_previous_version(no_error=True)
            else:
                self.validate_against_previous_version(no_error=True)
                # validates all of Content repo directories according to their schemas
                self.validate_all_files()
        else:
            self.validate_all_files()

        return self._is_valid

    def validate_against_previous_version(self, no_error=False):
        """Validate all files that were changed between previous version and branch_sha

        Args:
            no_error (bool): If set to true will restore self._is_valid after run (will not return new errors)
        """
        if self.prev_ver and self.prev_ver != 'master':
            print_color('Starting validation against {}'.format(self.prev_ver), LOG_COLORS.GREEN)
            modified_files, _, _ = self.get_modified_and_added_files(self.prev_ver)
            prev_self_valid = self._is_valid
            self.validate_modified_files(modified_files)
            if no_error:
                self._is_valid = prev_self_valid

    @staticmethod
    def add_sub_parser(subparsers):
        parser = subparsers.add_parser('validate', help='Validate your content files')
        parser.add_argument('-c', '--circle', type=str2bool, default=False, help='Is CircleCi or not')
        parser.add_argument('-b', '--backward-comp', type=str2bool, default=True,
                            help='To check backward compatibility.')
        parser.add_argument('-t', '--test-filter', type=str2bool, default=False,
                            help='Check that tests are valid.')
        parser.add_argument('-j', '--conf-json', action='store_true', help='Validate the conf.json file.')
        parser.add_argument('-i', '--id-set', action='store_true', help='Create the id_set.json file.')
        parser.add_argument('-p', '--prev-ver', help='Previous branch or SHA1 commit to run checks against.')
        parser.add_argument('-g', '--use-git', type=str2bool, default=True, help='Validate changes using git.')

    @staticmethod
    def _is_py_script_or_integration(file_path):
        file_yml = get_yaml(file_path)
        if re.match(INTEGRATION_REGEX, file_path, re.IGNORECASE):
            if file_yml.get('script', {}).get('type', 'javascript') != 'python':
                return False

            return True

        if re.match(SCRIPT_REGEX, file_path, re.IGNORECASE):
            if file_yml.get('type', 'javascript') != 'python':
                return False

            return True

        return False