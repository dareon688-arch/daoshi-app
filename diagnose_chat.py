"""诊断脚本：把所有私聊会话的成员情况打印出来，看“（对方已退出）”到底是怎么来的。
用法（服务器 app 目录、激活 venv 后）：python diagnose_chat.py
不改任何数据，只读不写。"""
from app import app, db, User, Conversation, Membership

with app.app_context():
    users = {u.id: u for u in User.query.all()}
    print(f"当前共有 {len(users)} 个用户：")
    for u in User.query.order_by(User.id).all():
        print(f"  id={u.id}  name={u.name!r}  status={u.status!r}  admin={u.is_admin}")

    print("\n所有私聊会话（is_group=False）：")
    privs = Conversation.query.filter_by(is_group=False).all()
    if not privs:
        print("  （没有私聊会话）")
    for c in privs:
        mems = Membership.query.filter_by(conversation_id=c.id).all()
        print(f"\n  会话 #{c.id}  成员数={len(mems)}")
        for m in mems:
            u = users.get(m.user_id)
            who = f"{u.name!r}(status={u.status!r})" if u else ">>> 用户不存在(孤儿) <<<"
            print(f"     membership#{m.id}  user_id={m.user_id} -> {who}")
