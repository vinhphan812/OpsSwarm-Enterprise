from opsswarm.commands import parse_command

def test_explicit_command_only():
    assert parse_command("rollback looks fine") is None
    c=parse_command("/opsswarm approve rollback\nextra")
    assert c.name=="approve" and c.argument=="rollback"

def test_unknown_command_is_not_authority():
    assert parse_command("/opsswarm maybe rollback") is None
