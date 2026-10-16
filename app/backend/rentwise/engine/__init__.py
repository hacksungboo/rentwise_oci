"""A 소유: 실제 해석·가용성·배정·검증 엔진.

여기에 contracts.EnginePort 를 만족하는 클래스를 구현하고 `RealEngine` 이름으로 노출하면,
환경변수 ENGINE_MODE=real 일 때 API가 이 구현을 주입한다 (rentwise/engine_registry.py).

    from rentwise.contracts import EnginePort, InterpretationInput, ...

    class RealEngine:
        mode = "real"
        def interpret(self, inp): ...
        def availability(self, inp): ...
        def solve(self, inp): ...
        def validate(self, snapshot, complete_candidate_plan): ...

규칙: DB·HTTP 접근 금지(interpret 의 모델 호출만 예외), 입력 mutate 금지.
B의 mock 구현(rentwise/dev_fakes/mock_engine.py)을 참고용으로 볼 수 있지만 복사하지 말 것.
"""
