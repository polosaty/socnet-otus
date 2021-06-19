box.cfg {}

binlog_pos = box.schema.space.create('binlog_pos', {id=512, if_not_exists=true})
binlog_pos:create_index('primary', {type="TREE", unique=true, parts={1, 'unsigned'}, if_not_exists=true})

user = box.schema.space.create('user', {id=516, if_not_exists=true})
user:create_index('primary', {type="TREE", unique=true, parts={1, 'unsigned'}, if_not_exists=true})


user:format({
    {name = 'id', type = 'unsigned', is_nullable=false},
    {name = 'username', type = 'string', is_nullable=false},
    {name = 'password', type = 'string', is_nullable=false},
    {name = 'firstname', type = 'string', is_nullable=false},
    {name = 'lastname', type = 'string'},
    {name = 'city', type = 'string'},
    {name = 'sex', type = 'string'},
    {name = 'interest', type = 'string'},
})


user_lastname_firstname_id = user:create_index('lastname_firstname_id', {
    type='TREE',
    unique = false,
    parts = {
        {field = 5, type = 'string'},
        {field = 4, type = 'string'},
        {field = 1, type = 'unsigned'},
    },
    if_not_exists=true
})

friend = box.schema.space.create('friend', {id=517, if_not_exists=true})
friend:format({
    {name = 'user_id', type = 'unsigned', is_nullable=false},
    {name = 'friend_id', type = 'unsigned', is_nullable=false},
})
friend:create_index('primary', {type="TREE", unique=true, parts={1, 'unsigned', 2, 'unsigned'}, if_not_exists=true})


function batch_insert(space, list)
    box.begin()
        for _, record in ipairs(list) do
            space:replace(record)
        end
    box.commit()
end


function is_subscriber(potencial_subscriber_id, current_user_id)
    -- user.id = f.user_id AND f.friend_id = %(current_user_id)s
    return 0 < #(box.space.friend.index.primary:select({potencial_subscriber_id, current_user_id}))
end

function is_friend(potencial_friend_id, current_user_id)
    -- user.id = f.friend_id AND f.user_id = %(current_user_id)s
    return 0 < #(box.space.friend.index.primary:select({current_user_id, potencial_friend_id}))
end


function search_with_friend_and_subscriber(prefix, current_user_id, limit, offset)
    local limit = limit or 21
    local offset = offset or 0
    local ret = {}
    local _time_to_yield = 0
    for _, tuple in box.space.user.index.lastname_firstname_id:pairs(
        {prefix, prefix}, {iterator='GE'}) do
        if (string.startswith(tuple[5], prefix, 1, -1)
            and string.startswith(tuple[4], prefix, 1, -1)) then
            if (offset > 0) then
                offset = offset - 1
            else
                user_id = tuple[1]
                table.insert(
                    ret, {
                        tuple,
                        {
                            is_subscriber(user_id, current_user_id),
                            is_friend(user_id, current_user_id)
                        }
                    }
                )
            end
        end
        if table.getn(ret) >= limit then
            return ret
        end

        _time_to_yield = _time_to_yield + 1
        if _time_to_yield > 1000 then
            _time_to_yield = 0
            require('fiber').yield()
        end
    end
    return ret
end

