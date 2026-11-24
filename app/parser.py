import json


def fixture_message(value):
    return json.dumps({'type': 'test_response', 'messages': [f'Test response: {value}']},
                      ensure_ascii=False)


def parse_message(message):
    data = json.loads(message)
    if not isinstance(data, dict) or data.get('type') != 'test_response':
        raise ValueError('Неизвестный формат тестового сообщения.')
    messages = data.get('messages')
    if not isinstance(messages, list) or not messages or not all(isinstance(x, str) for x in messages):
        raise ValueError('Ожидается непустой список текстовых сообщений.')
    return {'messages': messages}
