"""serving 模块入口：启动 AutoVisionAgent gRPC + 共享内存对外服务。"""
from serving.server import _build_arg_parser, serve


def main() -> None:
    args = _build_arg_parser().parse_args()
    serve(host=args.host, port=args.port, max_workers=args.max_workers)


if __name__ == "__main__":
    main()
