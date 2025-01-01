=========================
pytest-asyncio-concurrent
=========================

.. image:: https://img.shields.io/pypi/v/pytest-asyncio-concurrent.svg
    :target: https://pypi.org/project/pytest-asyncio-concurrent
    :alt: PyPI version

.. image:: https://img.shields.io/pypi/pyversions/pytest-asyncio-concurrent.svg
    :target: https://pypi.org/project/pytest-asyncio-concurrent
    :alt: Python versions

.. image:: https://codecov.io/github/czl9707/pytest-asyncio-concurrent/graph/badge.svg?token=ENWHQBWQML 
    :target: https://codecov.io/gh/czl9707/pytest-asyncio-concurrent
    :alt: Testing Coverage

.. image:: https://github.com/czl9707/pytest-asyncio-concurrent/actions/workflows/main.yml/badge.svg
    :target: https://github.com/czl9707/pytest-asyncio-concurrent/actions/workflows/main.yml
    :alt: See Build Status on GitHub Actions


System/Integration tests can take a really long time. 

And ``pytest-asyncio-concurrent`` A pytest plugin aiming to solve this by running asynchronous tests in true parallel, enabling faster execution for high I/O or network-bound test suites. 

Unlike ``pytest-asyncio``, which runs async tests **sequentially**, ``pytest-asyncio-concurrent`` takes advantage of Python's asyncio capabilities to execute tests **concurrently** by specifying **async group**.

Note: This plugin would more or less `Break Test Isolation Principle` \(for none function scoped fixture\). Please make sure your tests is ok to run concurrently before you use this plugin.


Key Features
------------

* Giving the capability to run pytest async functions.
* Providing granular control over Concurrency
  
  * Specifying Async Group to control tests that can run together. 
  * Specifying Timeout to avoid async tests taking forever. (Under Construction)

* Compatible with ``pytest-asyncio``.

Installation
------------

You can install "pytest-asyncio-concurrent" via `pip` from `PyPI`::

    $ pip install pytest-asyncio-concurrent


How this work?
--------------

This plugin extend ``pytest_runtestloop`` hook to handle async tests seperately.

In the 'async loop', tests are grouped by the `group` provided in the mark. and executed one group at a time.

In each group, instead of sequentially calling ``setup``, ``call``, ``teardown`` for individual test, these hooks are called for all tests in the group in batch.

The fixture lifecycle within group is handled by this plugin instead of pytest core, to work around pytest sequential test execution assumption.


Usage
-----

Run test Sequentially

.. code-block:: python

    @pytest.mark.asyncio_concurrent
    async def async_test_A():
        res = await wait_for_something_async()
        assert result.is_valid()

    @pytest.mark.asyncio_concurrent
    async def async_test_B():
        res = await wait_for_something_async()
        assert result.is_valid()


Run tests Concurrently

.. code-block:: python

    # the test below will run by itself
    @pytest.mark.asyncio_concurrent
    async def test_by_itself():
        res = await wait_for_something_async()
        assert result.is_valid()

    # the two tests below will run concurrently
    @pytest.mark.asyncio_concurrent(group="my_group")
    async def test_groupA():
        res = await wait_for_something_async()
        assert result.is_valid()

    @pytest.mark.asyncio_concurrent(group="my_group")
    async def test_groupB():
        res = await wait_for_something_async()
        assert result.is_valid()


Parametrized Tests

.. code-block:: python

    # the parametrized tests below will run sequential
    @pytest.mark.asyncio_concurrent
    @pytest.parametrize("p", [0, 1, 2])
    async def test_parametrize_sequential(p):
        res = await wait_for_something_async()
        assert result.is_valid()

    # the parametrized tests below will run concurrently
    @pytest.mark.asyncio_concurrent(group="my_group")
    @pytest.parametrize("p", [0, 1, 2])
    async def test_parametrize_concurrent():
        res = await wait_for_something_async()
        assert result.is_valid()


Contributing
------------

Contributions are very welcome. Tests can be run with ``tox``, please ensure
the coverage at least stays the same before you submit a pull request.

License
-------

Distributed under the terms of the ``MIT`` license, "pytest-asyncio-concurrent" is free and open source software
