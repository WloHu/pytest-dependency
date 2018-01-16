"""$DOC"""

__version__ = "$VERSION"
__revision__ = "$REVISION"

import pytest
import re

from inspect import getmembers
from collections import defaultdict

from typing import Iterable, Callable, Union, Mapping, Any

_automark = False
_ignore_unknown = False


CLASS_METHOD_SEPARATOR = '::'

CLASS_NAME = 'class_name'
FUNC_NAME = 'func_name'
PARAMS_NAME = 'params_name'

node_name_regexp = re.compile(
    (r'((?P<{}>\w+){})?'  # Optional class name group with separator.
     r'(?P<{}>\w+)'  # Function name.
     r'(\[(?P<{}>.*)\])?'  # Optional pytest-generated, parametrized test name in square brackets.
     ).format(CLASS_NAME, CLASS_METHOD_SEPARATOR, FUNC_NAME, PARAMS_NAME))


def _split_node_name(name):
    match_dict = node_name_regexp.match(name).groupdict()
    return match_dict[CLASS_NAME], match_dict[FUNC_NAME], match_dict[PARAMS_NAME]


def _get_bool(value):
    """Evaluate string representation of a boolean value.
    """
    if value:
        if value.lower() in ["0", "no", "n", "false", "f", "off"]:
            return False
        elif value.lower() in ["1", "yes", "y", "true", "t", "on"]:
            return True
        else:
            raise ValueError("Invalid truth value '%s'" % value)
    else:
        return False


class DependencyItemStatus(object):
    """Status of a test item in a dependency manager.
    """

    Phases = ('setup', 'call', 'teardown')
    passed_result_values = 3*('passed',)

    def __init__(self):
        self.results = {w: None for w in self.Phases}

    def __str__(self):
        l = ["%s: %s" % (w, self.results[w]) for w in self.Phases]
        return "Status(%s)" % ", ".join(l)

    def addResult(self, rep):
        self.results[rep.when] = rep.outcome

    def isSuccess(self):
        return tuple(self.results.values()) == self.passed_result_values

    def __bool__(self):
        return self.isSuccess()

    __nonzero__ = __bool__


class DependencyManager(object):
    """Dependency manager, stores the results of tests.
    """

    ScopeCls = {'module': pytest.Module, 'session': pytest.Session}

    @classmethod
    def getManager(cls, item, scope='module'):
        """Get the DependencyManager object from the node at scope level.
        Create it, if not yet present.
        """
        node = item.getparent(cls.ScopeCls[scope])
        if not hasattr(node, 'dependencyManager'):
            node.dependencyManager = cls()
        return node.dependencyManager

    def __init__(self):
        self.results = {}
        self.results_by_name = defaultdict(set)

    def addResult(self, item, dependency_name, rep):
        if item.cls:
            node_name = "{}{}{}".format(item.cls.__name__, CLASS_METHOD_SEPARATOR, item.name)
        else:
            node_name = item.name

        dependency_ids = (dependency_name,) + _split_node_name(node_name)

        dependency_status = self.results.setdefault(node_name, DependencyItemStatus())
        dependency_status.addResult(rep)

        for name in dependency_ids:
            if name:
                self.results_by_name[name].add(dependency_status)

    def checkDepend(self, dependencies, item, checker):
        unknown_ids, dependency_results = self._split_unknown_dependencies(dependencies)

        if not _ignore_unknown and unknown_ids:
            pytest.fail("Unknown dependencies {} in {}.".format(unknown_ids, item.name))

        if not checker(dependency_results):
            pytest.skip("{} depends on {}".format(item.name, dependencies))

    def _split_unknown_dependencies(self, dependencies):
        get_results = self.results_by_name.get

        unknown_ids = []
        dependency_results = []

        for id_ in dependencies:
            results = get_results(id_)
            if results is None:
                unknown_ids.append(id_)
            else:
                dependency_results.append(results)

        return unknown_ids, dependency_results


class MethodsMeta(type):
    def __init__(cls, name, bases, dict):
        type.__init__(cls, name, bases, dict)
        cls._methods = {name: attr for name, attr in getmembers(cls) if not name.startswith('_')}


class PassRequirement(object):
    __metaclass__ = MethodsMeta

    @staticmethod
    def all(dependency_results):
        # type: (Iterable[Iterable[bool]]) -> bool
        """Run dependent test if all tests in each dependency passed.

        :param dependency_results: Iterable of test results for each dependency.
        :return: `True` if all dependency sublist have only `True` values.

        """
        return all(all(results) for results in dependency_results)

    @staticmethod
    def any(dependency_results):
        # type: (Iterable[Iterable[bool]]) -> bool
        """Run dependent test if at least one test passed in any dependency.

        :param dependency_results: Iterable of test results for each dependency.
        :return: `True` if any dependency sublist has at lest one `True` value.

        """
        return any(any(results) for results in dependency_results)

    @staticmethod
    def each(dependency_results):
        # type: (Iterable[Iterable[bool]]) -> bool
        """Run dependent test if at least one test in each dependency passed.

        :param dependency_results: Iterable of test results for each dependency.
        :return: `True` if each dependency sublist has at lest one `True` value.

        """
        return all(any(results) for results in dependency_results)

    @classmethod
    def _get_requirement_callable(cls, name_of_callable):
        # type: (Union[str, Callable]) -> Callable
        """Returns requirement method specified by name or passes the value through if it is the
        correct requirement callable.

        :param name_of_callable: One of `PassRequirement` method names or the actual method object.
        :return: One of `PassRequirement` methods.

        """
        methods = cls._methods
        method = methods.get(name_of_callable, name_of_callable)

        if method not in methods.itervalues():
            message = "{} is not a <{}> method or its name.".format(name_of_callable, cls)
            raise ValueError(message)

        return method


def depends(request, other, xpassing=PassRequirement.all):
    """Add dependency on other test.

    Call pytest.skip() unless a successful outcome of all of the tests in
    other has been registered previously.  This has the same effect as
    the `depends` keyword argument to the :func:`pytest.mark.dependency`
    marker.  In contrast to the marker, this function may be called at
    runtime during a test.

    :param request: the value of the `request` pytest fixture related
        to the current test.
    :param other: dependencies, a list of names of tests that this
        test depends on.
    :type other: iterable of :class:`str`

    .. versionadded:: 0.2
    """
    _checkDepend(other, request.node, xpassing)


def _checkDepend(dependencies, item, xpassing):
    manager = DependencyManager.getManager(item)
    checker = PassRequirement._get_requirement_callable(xpassing)
    manager.checkDepend(dependencies, item, checker)


def pytest_addoption(parser):
    parser.addini("automark_dependency",
                  "Add the dependency marker to all tests automatically",
                  default=False)
    parser.addoption("--ignore-unknown-dependency",
                     action="store_true", default=False,
                     help="ignore dependencies whose outcome is not known")


def pytest_configure(config):
    global _automark, _ignore_unknown
    _automark = _get_bool(config.getini("automark_dependency"))
    _ignore_unknown = config.getoption("--ignore-unknown-dependency")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store the test outcome if this item is marked "dependency".
    """
    outcome = yield
    marker = item.get_marker("dependency")
    if marker is not None or _automark:
        rep = outcome.get_result()
        name = marker.kwargs.get('name') if marker is not None else None
        manager = DependencyManager.getManager(item)
        manager.addResult(item, name, rep)


def pytest_runtest_setup(item):
    """Check dependencies if this item is marked "dependency".
    Skip if any of the dependencies has not been run successfully.
    """
    marker = item.get_marker("dependency")
    if marker is not None:
        depends = marker.kwargs.get('depends')
        xpassing = marker.kwargs.get('xpassing', PassRequirement.all)
        if depends:
            _checkDepend(depends, item, xpassing)
