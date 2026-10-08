# This global belongs to store.users even when its authoring fragment moves.
PREFIX = 'user:'


def find_user(id):
    return PREFIX + str(id)
