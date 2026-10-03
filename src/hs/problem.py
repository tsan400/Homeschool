from dataclasses import dataclass, field


@dataclass
class Problem:
    prompt: str                 # Typst markup shown to the child
    answer: str                 # canonical plain-text key, e.g. "11/12", "2 3/4", "12 R3"
    form: str = "value"         # how answers are compared; see grade.check
    hint: str = "number"        # expected answer format, given to the handwriting reader
    steps: list[str] = field(default_factory=list)  # Typst lines for a worked example
