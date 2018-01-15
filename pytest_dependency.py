"""$DOC"""

__version__ = "$VERSION"
__revision__ = "$REVISION"

import pytest
import re

_automark = False
_ignore_unknown = False


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

CLASS_NAME = 'class_name'
FUNC_NAME = 'func_name'
PARAMS_NAME = 'params_name'
node_name_regexp = (r'((?P<{}>\w+)::)?'
                    r'(?P<{}>\w+)'
                    r'(\[(?P<{}>.*)\])?'
                    ).format(CLASS_NAME, FUNC_NAME, PARAMS_NAME)
regexpp = re.compile(node_name_regexp)
def _split_node_name(name):
    md = regexpp.match(name).groupdict()
    c, f, p = md[CLASS_NAME], md[FUNC_NAME], md[PARAMS_NAME]
    print c, f, p
    return c, f, p





class DependencyItemStatus(object):
    """Status of a test item in a dependency manager.
    """

    Phases = ('setup', 'call', 'teardown')

    def __init__(self):
        self.results = { w:None for w in self.Phases }

    def __str__(self):
        l = ["%s: %s" % (w, self.results[w]) for w in self.Phases]
        return "Status(%s)" % ", ".join(l)

    def addResult(self, rep):
        self.results[rep.when] = rep.outcome

    def isSuccess(self):
        return list(self.results.values()) == ['passed', 'passed', 'passed']

    def __bool__(self):
        return self.isSuccess()

    __nonzero__ = __bool__

from collections import defaultdict

class DependencyManager(object):
    """Dependency manager, stores the results of tests.
    """

    ScopeCls = {'module':pytest.Module, 'session':pytest.Session}

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
            node_name = "%s::%s" % (item.cls.__name__, item.name)
        else:
            node_name = item.name

        class_name, func_name, params_repr = _split_node_name(node_name)
        testcase_id = (dependency_name, class_name, func_name, params_repr)

        dependency_status = self.results.setdefault(testcase_id, DependencyItemStatus())
        dependency_status.addResult(rep)

        for name in testcase_id:
            if name:
                self.results_by_name[name].add(dependency_status)

    def checkDepend(self, dependencies, item, jajo):
        conditions[jajo](self, dependencies, item)


def _all(self, dependencies, item):
    for dependency_id in dependencies:
        results = self.results_by_name.get(dependency_id)
        if results:
            if all(results):
                continue
        else:
            if _ignore_unknown:
                continue
        pytest.skip("%s depends on %s" % (item.name, dependency_id))

def _any(self, dependencies, item):
    for dependency_id in dependencies:
        results = self.results_by_name.get(dependency_id)
        if results:
            if any(results):
                return
        else:
            if _ignore_unknown:
                continue
    pytest.skip("%s depends on %s" % (item.name, dependency_id))


def _each(self, dependencies, item):
    for dependency_id in dependencies:
        results = self.results_by_name.get(dependency_id)
        if results:
            if any(results):
                continue
        else:
            if _ignore_unknown:
                continue
        pytest.skip("%s depends on %s" % (item.name, dependency_id))


conditions = {
    'all': _all,
    'any': _any,
    'each': _each,
}


def depends(request, other, jajo='all'):
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
    _checkDepend(other, request.node, jajo)


def _checkDepend(dependencies, item, jajo='all'):
    manager = DependencyManager.getManager(item)
    manager.checkDepend(dependencies, item, jajo)


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
        jajo = marker.kwargs.get('jajo', 'all')
        if depends:
            _checkDepend(depends, item, jajo)

