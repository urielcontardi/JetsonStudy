def test_package_importable():
    import orwell_shared
    assert orwell_shared.__version__ == "0.1.0"
