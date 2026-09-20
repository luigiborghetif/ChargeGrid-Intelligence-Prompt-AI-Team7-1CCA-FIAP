"""Dashboard Plotly da operação ChargeGrid."""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from chargegrid.dados import Operacao
from chargegrid.indicadores import (
    LIMITE_ALERTA_KW,
    LIMITE_CRITICO_KW,
    IndicadoresOperacionais,
    calcular_indicadores,
)

CORES_STATUS = {
    "pico_critico": "#E24B4A",
    "atencao": "#EF9F27",
    "normal": "#639922",
    "ocioso": "#B4B2A9",
}

ROTULOS_STATUS = {
    "pico_critico": "Pico crítico",
    "atencao": "Atenção",
    "normal": "Normal",
    "ocioso": "Ocioso",
}


def _formatar_brl(valor: float) -> str:
    formatado = f"{valor:,.2f}"
    return "R$ " + formatado.replace(",", "_").replace(".", ",").replace("_", ".")


def _adicionar_kpis(
    figura: go.Figure,
    indicadores: IndicadoresOperacionais,
) -> None:
    kpis = (
        ("Sessões", str(indicadores.total_sessoes)),
        ("Energia entregue", f"{indicadores.energia_total_calculada_kwh:g} kWh"),
        ("Faturamento estimado", _formatar_brl(indicadores.faturamento_estimado_brl)),
        (
            "Pico de demanda",
            f"{indicadores.pico.potencia_kw:g} kW às {indicadores.pico.hora}",
        ),
    )

    posicoes_x = (0.02, 0.34, 0.66, 0.98)
    ancoras_x = ("left", "center", "center", "right")
    for (rotulo, valor), posicao_x, ancora_x in zip(
        kpis,
        posicoes_x,
        ancoras_x,
        strict=True,
    ):
        figura.add_annotation(
            x=posicao_x,
            y=1.16,
            xref="paper",
            yref="paper",
            xanchor=ancora_x,
            yanchor="middle",
            text=f"<span style='font-size:12px'>{rotulo}</span><br><b>{valor}</b>",
            showarrow=False,
            align="center",
            font={"size": 15, "color": "#30302E"},
            bgcolor="#F0F1F5",
            bordercolor="#D9DAE0",
            borderwidth=1,
            borderpad=8,
        )


def criar_dashboard(
    operacao: Operacao,
    indicadores: IndicadoresOperacionais | None = None,
) -> go.Figure:
    """Cria e retorna o dashboard sem abri-lo automaticamente."""
    if indicadores is None:
        indicadores = calcular_indicadores(operacao)

    infraestrutura = operacao.site.infraestrutura
    demanda_horaria = operacao.demanda_horaria
    carregadores = operacao.snapshot_carregadores.carregadores

    horas = [registro.hora for registro in demanda_horaria]
    demanda = [registro.potencia_media_kw for registro in demanda_horaria]
    ids = [carregador.id for carregador in carregadores]
    potencias = [carregador.potencia_kw for carregador in carregadores]
    energias = [carregador.energia_entregue_kwh for carregador in carregadores]
    sessoes = [carregador.total_sessoes for carregador in carregadores]
    cores = [CORES_STATUS[carregador.status] for carregador in carregadores]
    status = [ROTULOS_STATUS[carregador.status] for carregador in carregadores]

    figura = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Demanda ao longo do dia",
            "Potência por carregador no pico",
            "Energia entregue por carregador",
            "Sessões realizadas por carregador",
        ),
        vertical_spacing=0.18,
        horizontal_spacing=0.12,
    )

    figura.add_trace(
        go.Scatter(
            x=horas,
            y=demanda,
            mode="lines+markers",
            name="Demanda",
            line={"color": "#D85A30", "width": 3},
            marker={
                "size": [12 if valor > LIMITE_CRITICO_KW else 7 for valor in demanda],
                "color": [
                    "#A32D2D" if valor > LIMITE_CRITICO_KW else "#D85A30"
                    for valor in demanda
                ],
                "symbol": [
                    "diamond" if valor > LIMITE_CRITICO_KW else "circle"
                    for valor in demanda
                ],
            },
            fill="tozeroy",
            fillcolor="rgba(216, 90, 48, 0.08)",
            hovertemplate="%{x}: %{y:.1f} kW<extra></extra>",
        ),
        row=1,
        col=1,
    )

    figura.add_hline(
        y=infraestrutura.limite_demanda_contratada_kw,
        line={"color": "#E24B4A", "width": 1.5, "dash": "dash"},
        annotation_text=(
            f"Limite contratado: {infraestrutura.limite_demanda_contratada_kw:g} kW"
        ),
        annotation_position="top left",
        row=1,
        col=1,
    )
    figura.add_hline(
        y=LIMITE_ALERTA_KW,
        line={"color": "#EF9F27", "width": 1, "dash": "dot"},
        annotation_text=f"Alerta: {LIMITE_ALERTA_KW:g} kW",
        annotation_position="bottom left",
        row=1,
        col=1,
    )

    figura.add_annotation(
        x=indicadores.pico.hora,
        y=indicadores.pico.potencia_kw,
        text=(
            f"Pico: {indicadores.pico.potencia_kw:g} kW "
            f"({indicadores.pico.percentual_limite:g}%)"
        ),
        showarrow=True,
        arrowhead=2,
        arrowcolor="#A32D2D",
        ax=45,
        ay=-35,
        font={"color": "#A32D2D", "size": 11},
        row=1,
        col=1,
    )

    customdata = list(zip(status, strict=True))
    figura.add_trace(
        go.Bar(
            x=potencias,
            y=ids,
            orientation="h",
            name="Potência no pico",
            marker_color=cores,
            text=[f"{valor:g} kW" for valor in potencias],
            textposition="outside",
            customdata=customdata,
            hovertemplate=(
                "%{y}: %{x:.1f} kW<br>Status: %{customdata[0]}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    figura.add_vline(
        x=infraestrutura.potencia_unitaria_maxima_kw,
        line={"color": "#B4B2A9", "width": 1, "dash": "dash"},
        annotation_text=(f"Máximo: {infraestrutura.potencia_unitaria_maxima_kw:g} kW"),
        annotation_position="top left",
        row=1,
        col=2,
    )

    figura.add_trace(
        go.Bar(
            x=ids,
            y=energias,
            name="Energia entregue",
            marker_color=cores,
            text=[f"{valor:g}" for valor in energias],
            textposition="outside",
            customdata=customdata,
            hovertemplate=(
                "%{x}: %{y:.1f} kWh<br>Status: %{customdata[0]}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    figura.add_trace(
        go.Bar(
            x=ids,
            y=sessoes,
            name="Sessões",
            marker_color=cores,
            text=[str(valor) for valor in sessoes],
            textposition="outside",
            customdata=customdata,
            hovertemplate=(
                "%{x}: %{y} sessões<br>Status: %{customdata[0]}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    limite_eixo = max(
        infraestrutura.limite_demanda_contratada_kw,
        max(demanda),
    )
    figura.update_yaxes(
        title_text="Potência (kW)",
        range=[0, limite_eixo * 1.18],
        row=1,
        col=1,
    )
    figura.update_xaxes(title_text="Horário", row=1, col=1)
    figura.update_xaxes(title_text="Potência (kW)", row=1, col=2)
    figura.update_yaxes(title_text="Energia (kWh)", row=2, col=1)
    figura.update_yaxes(title_text="Sessões", rangemode="tozero", row=2, col=2)
    figura.update_xaxes(tickangle=-35, row=2, col=1)
    figura.update_xaxes(tickangle=-35, row=2, col=2)

    figura.update_xaxes(showgrid=False)
    figura.update_yaxes(gridcolor="rgba(136, 135, 128, 0.16)", gridwidth=0.5)
    figura.update_layout(
        title={
            "text": "ChargeGrid Intelligence — Operação do dia anterior",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 20},
        },
        height=780,
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"family": "Arial", "size": 12, "color": "#444441"},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
        },
        margin={"t": 170, "b": 60, "l": 60, "r": 60},
        hoverlabel={"bgcolor": "white", "font_size": 12},
    )
    _adicionar_kpis(figura, indicadores)

    return figura


def salvar_dashboard_html(figura: go.Figure, caminho: str | Path) -> Path:
    """Salva o dashboard como HTML autônomo e retorna o caminho criado."""
    destino = Path(caminho).expanduser().resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    figura.write_html(destino, include_plotlyjs=True, full_html=True)
    return destino
