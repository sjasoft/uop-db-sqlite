def test_basics(db_harness):
    """
    Test the basic functionality of the SQLite database.
    """
    db_harness.setup_random_data()
    db_harness.insert_and_check()
    db_harness.modify_and_check()
    db_harness.delete_and_check()
