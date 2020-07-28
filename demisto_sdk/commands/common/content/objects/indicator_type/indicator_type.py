from typing import Union

from wcmatch.pathlib import Path

from demisto_sdk.commands.common.content.objects.abstart_objects.json_content_object import JSONContentObject
from demisto_sdk.commands.common.constants import INDICATOR_TYPE


class IndicatorType(JSONContentObject):
    def __init__(self, path: Union[Path, str]):
        super().__init__(path, INDICATOR_TYPE)