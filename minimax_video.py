"""Minimal China-region MiniMax V1 video CLI; standard library only."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = 'https://api.minimax.cn'


class SafeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafeError('拒绝 HTTP 重定向；未转发鉴权信息。')


def open_request(request):
    # No retries, including POST; never log requests, headers or remote bodies.
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=60)


def api(path, payload=None):
    key = os.environ.get('MINIMAX_API_KEY')
    if not key or key == '<MINIMAX_API_KEY>' or '\n' in key or '\r' in key:
        raise SafeError('请通过环境的密钥管理配置 MINIMAX_API_KEY。')
    request = urllib.request.Request(
        BASE_URL + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        method='GET' if payload is None else 'POST')
    try:
        with open_request(request) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise SafeError(f'HTTP {exc.code}；未重试，响应正文不输出。') from None
    except (OSError, ValueError):
        raise SafeError('网络或响应格式错误；未重试。提交结果可能未知，请勿直接重新生成。') from None
    if not isinstance(result, dict) or not isinstance(result.get('base_resp'), dict):
        raise SafeError('缺少 API 状态；提交结果可能未知，请勿直接重新生成。')
    code = result['base_resp'].get('status_code')
    if type(code) is not int or code != 0:
        label = str(code) if type(code) is int else 'unknown'
        raise SafeError(f'API 业务错误 {label}；未重试，错误正文不输出。')
    return result


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,64}', value):
        raise SafeError('任务或文件 ID 必须为 1–64 位数字。')
    return value


def payload_for(args):
    if not args.prompt.strip() or len(args.prompt) > 2000:
        raise SafeError('prompt 必须为 1–2000 字符且不能全为空白。')
    if args.duration == 10 and args.resolution != '768P':
        raise SafeError('10 秒视频仅支持 768P。')
    return dict(model=args.model, prompt=args.prompt, duration=args.duration,
                resolution=args.resolution)


def submit(payload, journal):
    # Exclusive creation blocks accidental reruns with the same journal, even after
    # timeout or process interruption. This is a local guard, not API idempotency.
    with journal.open('x', encoding='utf-8') as file:
        json.dump({'state': 'submission_started_outcome_unknown'}, file)
        file.flush()
        os.fsync(file.fileno())
    result = api('/v1/video_generation', payload)
    task_id = identifier(result.get('task_id'))
    print('task_id=' + task_id, flush=True)
    journal.write_text(json.dumps({'state': 'submitted', 'task_id': task_id}) + '\n')


def query(task_id):
    task_id = identifier(task_id)
    result = api('/v1/query/video_generation?' + urllib.parse.urlencode({'task_id': task_id}))
    status = result.get('status')
    if status not in {'Preparing', 'Queueing', 'Processing', 'Success', 'Fail'}:
        raise SafeError('未知任务状态；未自动提交新任务。')
    summary = {'task_id': task_id, 'status': status}
    if status == 'Success':
        summary['file_id'] = identifier(result.get('file_id'))
    return summary


def download(file_id, output):
    file_id = identifier(file_id)
    if output.exists():
        raise SafeError('输出文件已存在；请选择新路径。')
    result = api('/v1/files/retrieve?' + urllib.parse.urlencode({'file_id': file_id}))
    info = result.get('file')
    url = info.get('download_url') if isinstance(info, dict) else None
    if not isinstance(url, str):
        raise SafeError('缺少下载地址。')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise SafeError('下载地址必须为不含用户信息的 HTTPS URL。')
    partial = output.with_name(output.name + '.part')
    # Never send the API credential to the storage host. Never log signed URLs.
    with partial.open('xb') as target:
        try:
            with open_request(urllib.request.Request(url)) as response:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        except (OSError, ValueError, SafeError):
            raise SafeError('下载未完成；保留 .part 文件，请检查后删除再重试下载。') from None
    # link() atomically refuses to overwrite an existing destination.
    os.link(partial, output)
    partial.unlink()
    print('视频已保存。')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    create = subs.add_parser('submit', help='默认离线校验；--execute 才提交付费任务')
    create.add_argument('--prompt', required=True)
    create.add_argument('--model', choices=['MiniMax-Hailuo-2.3', 'MiniMax-Hailuo-02'], default='MiniMax-Hailuo-2.3')
    create.add_argument('--duration', type=int, choices=[6, 10], default=6)
    create.add_argument('--resolution', choices=['768P', '1080P'], default='768P')
    create.add_argument('--execute', action='store_true', help='明确同意提交付费生成')
    create.add_argument('--journal', type=Path, default=Path('submission.json'))
    status = subs.add_parser('query', help='仅查询已有任务一次，不自动轮询或生成')
    status.add_argument('--task-id', required=True)
    save = subs.add_parser('download', help='按成功任务的 file_id 获取并保存视频')
    save.add_argument('--file-id', required=True)
    save.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'submit':
            payload = payload_for(args)
            if not args.execute:
                print('参数校验通过；未读取密钥，未联网，未提交。')
            else:
                submit(payload, args.journal)
        elif args.command == 'query':
            print(json.dumps(query(args.task_id), ensure_ascii=False))
        else:
            download(args.file_id, args.output)
        return 0
    except FileExistsError:
        print('错误：记录或目标文件已存在；不会重复提交或覆盖。', file=sys.stderr)
    except SafeError as exc:
        print('错误：' + str(exc), file=sys.stderr)
    except (OSError, ValueError):
        print('错误：本地文件或数据处理失败；未重试。若已提交，请检查任务记录。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
