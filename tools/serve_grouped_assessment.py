"""Add a prepared group catalog to the existing assessment without changing its session or billing identity."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]

from commentscope.factory.claim_clusters import sha
from commentscope.product.web import ProductServer
from tools.serve_assessment_credit import build, experiment_lock
from tools.perspective_groups.catalog import load_record, read


def add_catalog(product, path, checksum):
    if sha(path) != checksum:
        raise ValueError('Unexpected grouped catalog checksum')
    analysis = load_record(read(path))
    analysis.live()
    if analysis.id in product.analyses:
        raise ValueError('Duplicate grouped analysis')
    product.analyses = {analysis.id:analysis, **product.analyses}
    return analysis


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--catalog',required=True,type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--public-origin',required=True)
    args=parser.parse_args()
    os.chdir(ROOT)
    directory=args.directory.resolve()
    with experiment_lock(directory):
        product, legacy, _ = build(directory)
        try:
            add_catalog(product,args.catalog,args.sha256)
            with ProductServer(product,legacy,args.port,public_origin=args.public_origin) as server:
                server.serve_forever()
        finally:
            product.close()


if __name__ == '__main__':
    main()
