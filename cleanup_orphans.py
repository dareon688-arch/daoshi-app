"""一次性清理脚本：删除“孤儿会话”——即成员已被删号、对方账号不存在的残留私聊。
症状：消息页里出现昵称为“（对方已退出）”的会话。

用法（在服务器 app 目录下、激活 venv 后）：
    python cleanup_orphans.py          # 先看看会删哪些（演练，不真删）
    python cleanup_orphans.py --yes    # 确认无误后，真正执行删除

逻辑：
  1) 删掉 user_id 指向已不存在用户的 Membership（孤儿成员记录）
  2) 删掉清理后成员数 < 2 的私聊会话（一个人都不剩、或只剩一个人的私聊都没意义）
  3) Conversation 已设级联，删会话会自动带走它的消息和剩余成员记录
"""
import sys
from app import app, db, User, Conversation, Membership

DRY_RUN = "--yes" not in sys.argv


def main():
    with app.app_context():
        valid_user_ids = {u.id for u in User.query.all()}

        # 1) 找出指向“已不存在用户”的成员记录
        orphan_mems = [m for m in Membership.query.all()
                       if m.user_id not in valid_user_ids]
        print(f"发现 {len(orphan_mems)} 条孤儿成员记录（指向已删除的用户）")

        affected_conv_ids = {m.conversation_id for m in orphan_mems}

        if not DRY_RUN:
            for m in orphan_mems:
                db.session.delete(m)
            db.session.flush()   # 先落地，便于下面重新统计每个会话剩几个人

        # 2) 受影响的私聊里，成员 < 2 的整条删掉
        to_delete_convs = []
        for cid in affected_conv_ids:
            conv = db.session.get(Conversation, cid)
            if not conv:
                continue
            remaining = Membership.query.filter_by(conversation_id=cid).count()
            # DRY_RUN 时还没删孤儿成员，得手动减去
            if DRY_RUN:
                remaining -= sum(1 for m in orphan_mems if m.conversation_id == cid)
            if (not conv.is_group) and remaining < 2:
                to_delete_convs.append(conv)

        print(f"将删除 {len(to_delete_convs)} 个空壳私聊会话"
              f"（连同其消息一并清除）")
        for conv in to_delete_convs:
            print(f"  - 会话 #{conv.id}")

        if DRY_RUN:
            print("\n[演练模式] 没有真正删除。确认无误后运行：python cleanup_orphans.py --yes")
            return

        for conv in to_delete_convs:
            db.session.delete(conv)   # 级联删除其消息和剩余成员记录
        db.session.commit()
        print("\n✅ 清理完成。")


if __name__ == "__main__":
    main()
