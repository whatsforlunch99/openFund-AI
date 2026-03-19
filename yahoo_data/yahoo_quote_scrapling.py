#!/usr/bin/env python3
from yahoo_quote_core import cli_main
import yahoo_quote_pages as page


if __name__ == "__main__":
    cli_main(page, page.OUT_PATH)
