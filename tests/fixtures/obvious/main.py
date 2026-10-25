from pathlib import Path

INVOICE_DIRECTORY = Path("C:/Users/developer/Desktop/invoices")


def invoice_count():
    return len(list(INVOICE_DIRECTORY.iterdir()))


if __name__ == "__main__":
    print(invoice_count())
