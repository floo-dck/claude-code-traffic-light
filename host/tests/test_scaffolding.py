"""Guards the assumptions the rest of the test suite is built on."""

import serial

import trafficlight


def test_package_is_importable():
    assert trafficlight.__doc__


def test_pyserial_is_available():
    # The host CLI cannot do anything without it, so fail loudly and early.
    assert hasattr(serial, "Serial")
