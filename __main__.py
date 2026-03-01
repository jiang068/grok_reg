"""Module entrypoint for grok_reg package.

Provides a CLI shim similar to the original project.
"""
import argparse


def cli():
    # suppress ResourceWarning as in original project
    import warnings
    warnings.simplefilter("ignore")

    parser = argparse.ArgumentParser(description="grok_reg 半自动注册器")
    parser.add_argument('--threads', type=int, default=None, help='并发线程数 (默认使用 config.THREADS)')
    parser.add_argument('--total-tasks', type=int, default=None, help='总任务数（总共要执行的任务数），默认等于 threads')
    args = parser.parse_args()

    # 如果没有通过命令行指定，交互式询问用户（仅在终端运行时）
    try:
        if args.threads is None:
            raw = input("请输入并发线程数（回车使用默认值 config.THREADS）: ").strip()
            if raw:
                try:
                    args.threads = int(raw)
                except Exception:
                    print("无效的线程数输入，使用默认配置")
                    args.threads = None
        if args.total_tasks is None:
            raw2 = input("请输入总任务数（回车使用与线程数相同或默认值）: ").strip()
            if raw2:
                try:
                    args.total_tasks = int(raw2)
                except Exception:
                    print("无效的总任务数输入，使用默认配置")
                    args.total_tasks = None
    except Exception:
        # 在非交互式环境（例如被其它工具调用）忽略提示
        pass

    # import here to avoid heavy imports at module import time
    try:
        # 如果用户通过 CLI 指定了 total_tasks，先设置环境变量，保证在 config 被导入时生效
        import os
        if args.total_tasks is not None:
            os.environ['TOTAL_TASKS'] = str(args.total_tasks)

        from .registrar.registrar import main
    except Exception as e:
        raise

    main(threads=args.threads)


if __name__ == '__main__':
    cli()
