from django import forms
from django.conf import settings
import psycopg2
import sqlite3
from biostar.recipes import const
from . import models

# Share the logger with models.
logger = models.logger


def float_field(data):
    numrange = data.get("range", [1.0, 100000.0])
    min_value, max_value = numrange[0], numrange[1]

    label = data.get("label")
    widget = forms.NumberInput()
    help_text = data.get("help", f"Enter number between {min_value} and {max_value}")
    initial = data.get("value", 1)

    field = forms.FloatField(widget=widget, initial=initial, min_value=min_value, max_value=max_value,
                             help_text=help_text, label=label, required=False)

    return field


def select_field(data, choicefunc=None):
    if choicefunc:
        choices = choicefunc() or []
    else:
        choices = data.get("choices", [])

    initial = data.get("value", "")
    label = data.get("label", "")
    help_text = data.get("help", "")

    widget = forms.Select(choices=choices, attrs={"class": "ui dropdown"})
    field = forms.CharField(widget=widget, initial=initial, label=label, help_text=help_text)

    return field


def char_field(data):

    initial = data.get("value", "")
    label = data.get("label", "")
    help_text = data.get("help", "")

    field = forms.CharField(initial=initial, label=label, help_text=help_text, max_length=32,
                            required=False)

    return field


def radioselect_field(obj):
    choices = obj.get("choices", [])
    initial = obj.get("value", "")
    label = obj.get("label", "")
    help_text = obj.get("help", "")

    widget = forms.RadioSelect(choices=choices)
    field = forms.CharField(widget=widget, initial=initial, label=label, help_text=help_text)

    return field


def db_connect(database_name=''):

    database_name = database_name or settings.DATABASE_NAME
    try:
        conn = psycopg2.connect(database=database_name)
    except Exception as exc:
        logger.error(f'Error connecting to postgres database: {exc}')
        conn = sqlite3.connect(database_name)

    return conn


def fetch_from_db(columns, table, database_name):

    # Final query string to execute
    query_str = f'SELECT {columns} FROM {table}'
    try:
        # connect to the database.
        db = db_connect(database_name=database_name)
        cursor = db.cursor()
        cursor.execute(query_str)

    except Exception as exec:
        logger.error(f"Error with database: {exec}")
        return

    if cursor.rowcount:
        colnames = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        mapped = [{col_name: val for val, col_name in zip(row, colnames)} for row in rows]
        db.close()
        return mapped

    return


def sql_field(obj, project=None):

    # White list of allowed tables
    allowed_tables = ['data']

    # Dictionary to construct query from
    table = obj.get("table", 'recipes_data')
    columns = obj.get("columns", '*')

    # Database to connect to, selects default database otherwise.
    database_name = obj.get('database_name', '')
    return_value = obj.get('return_value', 'file')

    display_value = obj.get('display_value', 'name')
    label = obj.get("label", 'sql field')
    help_text = obj.get("help", 'Pick an option.')

    # Final query string.
    query_list = fetch_from_db(columns=columns, table=table, database_name=database_name)

    if not query_list:
        return

    # The columns we want to pick and "Return".
    # These values will populate the template.
    choices = [(val.get(return_value), val.get(display_value)) for val in query_list]

    widget = forms.Select(choices=choices, attrs={"class": "ui dropdown"})

    field = forms.CharField(widget=widget, label=label, help_text=help_text)
    return field


def number_field(data):
    numrange = data.get("range", [0, 1])
    min_value, max_value = min(numrange), max(numrange)
    label = data.get("label", "")
    widget = forms.NumberInput()
    help_text = data.get("help", f"Range: {min_value} and {max_value}")
    initial = data.get("value", 0)

    field = forms.IntegerField(
        label=label, initial=initial, min_value=min_value, max_value=max_value,
        help_text=help_text, widget=widget
    )

    return field


def checkbox_field(data):
    label = data.get("label", "")
    help_text = data.get("help", "")
    initial = data.get("value", False)
    widget = forms.CheckboxInput(attrs={'class':"ui checkbox"})

    field = forms.BooleanField(initial=initial, widget=widget, label=label, help_text=help_text, required=False)

    return field


def data_field_generator(field, project, type="", extras=[]):
    """
    Generates a SELECT field populated by data names that
    are of a certain type.
    """

    query = models.Data.objects.filter(project=project)
    if type:
        type = type.replace(" ", '')
        query = query.filter(type__iregex=type)

    query = query.order_by("rank", "-date")

    # Create a mapping of data to id.
    datamap = dict((obj.id, obj) for obj in query)

    # The choice generator.
    def choice_func():
        choices = extras + [(d.id, d.name) for d in datamap.values()]
        return choices

    # Returns a SELECT field with the choices.
    return select_field(field, choicefunc=choice_func)


def dynamic_field(data, project=None):
    """
    Creates a DJANGO form field from a dictionary.
    """

    # Get the known field types.
    field_types = get_field_types(project=project)

    if not hasattr(data, 'get'):
        # Not a "dictionary-like" data
        return None

    # Find out the display type.
    display_type = data.get("display")

    # Fields with no display type are not visible.
    if not display_type:
        return None

    # Data should be selected from a project or directrly from database.
    from_project = (data.get("source") == "PROJECT")
    extras = data.get("extras", [])
    if from_project and project:
        # Project specific data should have a type.
        data_type = data.get("type", "").strip() or ""

        if isinstance(data_type, dict):
            data_type = data_type.get("symbol", "").strip() or ""

        field = data_field_generator(data, project=project, type=data_type, extras=extras)

    else:
        # In all other cases we generate a field from the tupe.
        func = field_types.get(display_type)
        if not func:
            logger.error(f"Invalid display type={display_type}")
            return None
        field = func(data)

    return field


def get_field_types(project=None):
    """
    Maps strings constants to field types.
    """

    sqlfield = lambda obj: sql_field(project=project, obj=obj)
    field_types = {
        const.RADIO: radioselect_field,
        const.DROPDOWN: select_field,
        const.INTEGER: number_field,
        const.TEXTBOX: char_field,
        const.FLOAT: float_field,
        const.CHECKBOX: checkbox_field,
        const.SQL: sqlfield
    }

    return field_types
