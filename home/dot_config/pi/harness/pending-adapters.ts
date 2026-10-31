// 保留 (非同期承認) に対応する操作のアダプタの登録表 (CHG-0055)。今は空。操作ごとの feature (git_integrate など) が、ここに足す。
// 要求の側 (PENDING_ADAPTERS: 前提の取得) と、承認の側 (APPROVAL_ADAPTERS: 計画・再検査・実行) は別の型。
// 登録のない操作は、「あとで」も出さず従来どおり。
import type { PendingAdapter } from "./actions.ts";
import type { ApprovalAdapter } from "./pending-approve.ts";

export const PENDING_ADAPTERS: Record<string, PendingAdapter> = {};
export const APPROVAL_ADAPTERS: Record<string, ApprovalAdapter> = {};
