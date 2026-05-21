from splicer.logging import setup_logging


def main():
    logger = setup_logging()
    logger.info("Hello from splicer!")


if __name__ == "__main__":
    main()
