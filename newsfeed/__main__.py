import json

from .archive import maintain

if __name__ == "__main__":
    print(json.dumps(maintain(), indent=2))
