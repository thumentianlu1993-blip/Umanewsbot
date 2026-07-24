# Re-export legacy tests from the single-file module so that test discovery
# finds both the old test classes and the new test files in this package.
from stable.tests_legacy import *  # noqa: F401, F403
