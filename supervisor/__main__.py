"""python -m supervisor 지원"""

import asyncio
from .supervisor import main

if __name__ == "__main__":
    asyncio.run(main())
