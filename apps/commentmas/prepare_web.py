"""Prepare cached English Step1 copy from validated analysis using the configured model."""
import argparse
from llm_client import create_client, read_settings
from web_data import DEFAULT_DATA, WebData

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=str(DEFAULT_DATA))
    args = parser.parse_args()
    client = create_client(read_settings())
    catalog = WebData(args.data, client).prepare()
    print(f"English catalog ready: {len(catalog['agents'])} agents; {client.requests} new model requests.")
