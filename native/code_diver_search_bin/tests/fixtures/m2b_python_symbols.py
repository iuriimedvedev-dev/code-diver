"""Module documentation is not a symbol."""

@registry("service", enabled=True)
class Outer:
    @staticmethod
    def build(value: str = "x"):
        def helper():
            return value
        return helper()

    class Inner:
        async def run(self):
            return None

    if True:
        def conditional(): pass

@decorate(
    "two",
    count=2,
)
async def task(
    value: int,
):
    """Function documentation is not a symbol."""
    return value

def stub(): ...