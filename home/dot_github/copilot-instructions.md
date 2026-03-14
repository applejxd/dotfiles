# GitHub Copilot Instructions

高品質なエンジニアリングと徹底したテストを重視して開発を進めてください。

## 開発の原則
- **TDD (Test Driven Development)** を基本とし、実装前にテストを記述・更新します。
- コードは読みやすく、保守性が高い状態を維持してください。
- 変更、意思決定に関しては適切にドキュメント（`docs/` や ADR）を更新してください。

## Agentic Mode Goals

### Plan Mode
- **最終ゴール**: 実装計画および詳細なテスト計画を含む **ADR (Architecture Decision Record)** の作成。
- ユーザーの承認を得るまで、設計の整合性とテスト容易性を検証してください。

### Auto-pilot Mode (Execution/Verification)
- **最終ゴール**:
  - **単体テスト100%通過**
  - **統合テストの完全な通過**
- 実装完了後、必ず検証を行い、品質が担保されていることを実証してください。
