from .users import find_user


def order_for_user(id):
    return {'user': find_user(id), 'status': 'pending'}
