class Themes:
    GREEN = "green"
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    DIM = "dim"
    
    @staticmethod
    def pnl_color(value: float) -> str:
        if value > 0:
            return "green"
        if value < 0:
            return "red"
        return "dim"

    @staticmethod
    def status_indicator(connected: bool) -> str:
        return "[green]●[/green]" if connected else "[red]●[/red]"
